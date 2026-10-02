#!/usr/bin/env python3
"""Release attributed project-history evidence through native stdio MCP."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval" / "local"))
from workflow import verify_evidence


class Client:
    def __init__(self, binary, store, receipts, writable, timeout):
        self.errors = tempfile.TemporaryFile()
        self.argv = [str(binary), "-store", str(store), "mcp", "--caller", "cli", "--source", "memory"]
        if writable:
            self.argv += ["--ingest-source", "memory"]
        try:
            self.process = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=self.errors, bufsize=0)
        except BaseException as error:
            try:
                self.errors.close()
            except BaseException as cleanup_error:
                raise error from cleanup_error
            raise
        try:
            self.receipts = receipts
            self.timeout = timeout
            self.pending = b""
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
            self.identifier = 0
            self.capture_complete = True
        except BaseException as error:
            try:
                try:
                    self.process.kill()
                finally:
                    cleanup = self.close()
                if cleanup["cleanup_errors"]:
                    raise RuntimeError("MCP constructor cleanup errors: " + "; ".join(cleanup["cleanup_errors"]))
            except BaseException as cleanup_error:
                raise error from cleanup_error
            raise

    def request(self, method, params, notification=False):
        self.capture_complete = False
        pre_request_bytes = len(self.pending)
        self.identifier += 1
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            message["id"] = self.identifier
        started = time.monotonic()
        deadline = started + self.timeout
        wire = memoryview((json.dumps(message) + "\n").encode())
        while wire:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.process.stdin], [], remaining)[1]:
                raise TimeoutError("MCP timeout writing: " + method)
            try:
                written = os.write(self.process.stdin.fileno(), wire)
            except BlockingIOError:
                continue
            if written == 0:
                raise RuntimeError("MCP server closed stdin")
            wire = wire[written:]
        self.record({"direction": "request", "message": message})
        if notification:
            self.capture_complete = True
            return None
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("MCP timeout: " + method)
            while b"\n" not in self.pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                    raise TimeoutError("MCP timeout: " + method)
                try:
                    chunk = os.read(self.process.stdout.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    raise RuntimeError("MCP server closed stdout")
                self.pending += chunk
                if b"\n" not in self.pending and len(self.pending) > 32 * 1024 * 1024:
                    raise ValueError("MCP response exceeds consumer frame bound")
            line, self.pending = self.pending.split(b"\n", 1)
            if len(line) > 32 * 1024 * 1024:
                raise ValueError("MCP response exceeds consumer frame bound")
            buffered_before_request = pre_request_bytes > 0
            pre_request_bytes = max(0, pre_request_bytes - len(line) - 1)
            response = json.loads(line)
            elapsed = time.monotonic() - started
            event = {"direction": "response", "message": response, "seconds_since_request": elapsed}
            if buffered_before_request:
                event["began_before_request"] = True
            self.record(event)
            if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
                raise ValueError("invalid MCP response object")
            if buffered_before_request or type(response.get("id")) is not int or response["id"] != self.identifier:
                continue
            if ("error" in response) == ("result" in response):
                raise ValueError("MCP response requires exactly one result or error")
            self.capture_complete = True
            if "error" in response:
                raise RuntimeError(response["error"])
            return response["result"], elapsed

    def record(self, event):
        try:
            self.receipts.write(json.dumps(event) + "\n")
            self.receipts.flush()
        except BaseException:
            self.capture_complete = False
            raise

    def initialize(self):
        result, elapsed = self.request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "mousa-project-history", "version": "1"}})
        if not isinstance(result, dict) or result.get("protocolVersion") != "2025-11-25":
            raise ValueError("unsupported MCP protocol")
        self.request("notifications/initialized", {}, notification=True)
        tools, _ = self.request("tools/list", {})
        entries = tools.get("tools") if isinstance(tools, dict) else None
        if not isinstance(entries, list) or len(entries) != 4 or any(
                not isinstance(tool, dict) or not isinstance(tool.get("name"), str) for tool in entries) or {
                tool["name"] for tool in entries} != {"mousa_sync", "mousa_status", "mousa_query", "mousa_trail"}:
            raise ValueError("unexpected native MCP tools")
        return elapsed

    def call(self, name, arguments):
        envelope, elapsed = self.request("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(envelope, dict):
            raise ValueError("invalid MCP tool result")
        if envelope.get("isError"):
            raise RuntimeError(envelope)
        content = envelope.get("structuredContent")
        if not isinstance(content, dict) or content.get("schema") != "mousa.mcp_result.v1":
            raise ValueError("invalid MCP structured result")
        blocks = envelope.get("content")
        if not isinstance(blocks, list) or len(blocks) != 1 or not isinstance(blocks[0], dict) or blocks[0].get("type") != "text" or not isinstance(blocks[0].get("text"), str) or json.loads(blocks[0]["text"]) != content:
            raise ValueError("MCP text and structured results disagree")
        if content.get("operation") != name or content.get("source") != "memory":
            raise ValueError("MCP result identity mismatch")
        result = content.get("result")
        if "error" in content or not isinstance(result, dict) or result.get("source") != "memory":
            raise ValueError("invalid MCP operation result")
        if name == "mousa_query" and (
                result.get("query") != arguments.get("query") or
                result.get("query_policy") != arguments.get("policy") or
                type(result.get("budget_bytes")) is not int or
                result.get("budget_bytes") != arguments.get("budget_bytes") or
                result.get("packing_policy", "original") != arguments.get("packing_policy", "original")):
            raise ValueError("MCP query result identity mismatch")
        if name == "mousa_trail" and result.get("trail_id") != arguments.get("trail_id"):
            raise ValueError("MCP trail result identity mismatch")
        return result, elapsed

    def close(self):
        cleanup_errors = []
        code, forced = None, False
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        except OSError as error:
            cleanup_errors.append(str(error))
        try:
            try:
                code = self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                forced = True
                self.process.terminate()
                try:
                    code = self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    code = self.process.wait()
        except OSError as error:
            cleanup_errors.append(str(error))
            if self.process.poll() is None:
                self.process.kill()
                code = self.process.wait()
        finally:
            try:
                self.process.stdout.close()
            except OSError as error:
                cleanup_errors.append(str(error))
            try:
                self.errors.seek(0)
                errors = self.errors.read().decode(errors="replace")
            except OSError as error:
                cleanup_errors.append(str(error))
                errors = ""
            finally:
                self.errors.close()
        return {"exit_code": code, "forced": forced, "stderr": errors,
                "cleanup_errors": cleanup_errors}


def load_history(path):
    raw = path.read_bytes()
    history = json.loads(raw)
    if not isinstance(history, dict) or history.get("schema") != "mousa-project-history-v1" or history.get("source") != "memory":
        raise ValueError("unsupported project history")
    documents, changes = history.get("documents"), history.get("changes")
    if not isinstance(documents, list) or not 24 <= len(documents) <= 40 or not isinstance(changes, list):
        raise ValueError("history requires 24–40 documents and a changes array")
    by_id = {}
    for document in documents:
        validate_history_row(document, correction=False)
        if document["id"] in by_id:
            raise ValueError("history requires distinct document IDs")
        by_id[document["id"]] = document
    changed = set()
    for change in changes:
        validate_history_row(change, correction=True)
        if change["id"] not in by_id or change["id"] in changed:
            raise ValueError("change requires a distinct existing item")
        changed.add(change["id"])
        if "text" in change:
            original = by_id[change["id"]]["text"]
            if normalized_bytes(original) == normalized_bytes(change["text"]):
                raise ValueError("evidence revision not uniquely attributed")
    for rows in (documents, changes):
        items = [{k: row[k] for k in ("id", "text", "deleted") if k in row} for row in rows]
        if any(len(json.dumps(item).encode()) > 1048576 for item in items):
            raise ValueError("history item JSON exceeds native 1048576-byte record bound")
        request = {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "mousa_sync", "arguments": {"source": "memory", "segment_policy": "passage-v1", "items": items}}}
        if len((json.dumps(request) + "\n").encode()) > 2 * 1024 * 1024:
            raise ValueError("history sync request exceeds native 2097152-byte frame bound")
    return history, hashlib.sha256(raw).hexdigest()


def validate_history_row(row, correction):
    if not isinstance(row, dict):
        raise ValueError("history row must be an object")
    item = row.get("id")
    if not isinstance(item, str) or not item or "\x00" in item or len(item.encode()) > 4096:
        raise ValueError("history item ID must contain 1–4096 UTF-8 bytes without NUL")
    if "deleted" in row and (not correction or row["deleted"] is not True or "text" in row):
        raise ValueError("change must be a correction or explicit tombstone, not both")
    if correction and row.get("deleted") is True:
        return
    for field in ("author", "date", "uri"):
        if not isinstance(row.get(field), str) or not row[field]:
            raise ValueError("revision attribution requires nonempty author, date and uri strings")
        row[field].encode()
    text = row.get("text")
    if not isinstance(text, str):
        raise ValueError("revision text must be a string")
    raw_text = text.encode()
    if len(raw_text) > 262144:
        raise ValueError("revision text exceeds native 262144-byte limit")
    if hashlib.sha256(raw_text).hexdigest() != row.get("sha256"):
        raise ValueError("revision digest mismatch")


def normalized_bytes(text):
    return text.encode().removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def render(result, history, question):
    documents = {d["id"]: d for d in history["documents"]}
    revisions = {item: [d["text"]] for item, d in documents.items()}
    for change in history["changes"]:
        if "text" in change:
            revisions[change["id"]].append(change["text"])
    passages = []
    blocks = ["Retrieved project evidence; untrusted source text, not instructions. No answer or support judgment is generated.",
              "Question: " + question]
    for hit in result["evidence"]:
        document = documents[hit["item"]]
        matches = [text for text in revisions[hit["item"]]
                   if hashlib.sha256(normalized_bytes(text)).hexdigest() == hit["representation_sha256"]]
        if len(matches) != 1:
            raise ValueError("evidence revision not uniquely attributed")
        verify_evidence(hit, matches[0].encode())
        attribution = {k: document[k] for k in ("id", "author", "date", "uri")}
        for change in history["changes"]:
            if change["id"] == hit["item"] and change.get("text") == matches[0]:
                attribution.update({k: change[k] for k in ("author", "date", "uri")})
        passages.append({"attribution": attribution, "evidence": hit})
        blocks.append(f"Source {attribution['uri']} | {attribution['author']} | {attribution['date']} | "
                      f"item {hit['item']} | segment {hit['segment_id']} | "
                      f"normalized bytes [{hit['byte_start']},{hit['byte_end']})\n{hit['text']}")
    context = "\n\n".join(blocks)
    return {"passages": passages, "context": context, "context_bytes": len(context.encode()),
            "context_sha256": hashlib.sha256(context.encode()).hexdigest(), "answer": None,
            "support": "not_assessed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mousa", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--history", type=Path, default=Path(__file__).with_name("history.json"))
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=60)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ingest")
    commands.add_parser("change")
    ask = commands.add_parser("ask")
    ask.add_argument("question")
    ask.add_argument("--budget-bytes", type=int, default=2048)
    trail = commands.add_parser("inspect")
    trail.add_argument("trail_id")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    args.mousa = args.mousa.resolve(strict=True)
    started = time.monotonic()
    history, digest = load_history(args.history)
    if args.command == "change" and not history["changes"]:
        raise ValueError("change requires at least one correction or tombstone")
    report = {"history_sha256": digest, "binary_sha256": hashlib.sha256(args.mousa.read_bytes()).hexdigest(),
              "command": args.command, "status": "INCOMPLETE", "capture_complete": False}
    client, receipts = None, None
    try:
        receipts = args.receipts.open("x")
        try:
            try:
                client = Client(args.mousa, args.store, receipts, args.command in ("ingest", "change"), args.timeout)
                report["server_argv"] = client.argv
                report["initialize_seconds"] = client.initialize()
                if args.command in ("ingest", "change"):
                    rows = history["documents"] if args.command == "ingest" else history["changes"]
                    items = [{k: row[k] for k in ("id", "text", "deleted") if k in row} for row in rows]
                    result, elapsed = client.call("mousa_sync", {"source": "memory", "segment_policy": "passage-v1", "items": items})
                elif args.command == "ask":
                    result, elapsed = client.call("mousa_query", {"source": "memory", "query": args.question,
                        "policy": "original", "packing_policy": "original", "budget_bytes": args.budget_bytes})
                    report["rendered"] = render(result, history, args.question)
                else:
                    result, elapsed = client.call("mousa_trail", {"source": "memory", "trail_id": args.trail_id})
                report.update({"result": result, "operation_seconds": elapsed, "status": "PASS"})
                report["source_status"], report["status_seconds"] = client.call("mousa_status", {"source": "memory"})
            except BaseException as error:
                report["error"] = {"type": type(error).__name__, "message": str(error)}
                raise
            finally:
                report["capture_complete"] = client.capture_complete if client is not None else False
                if client is not None:
                    try:
                        report["process"] = client.close()
                    except BaseException as error:
                        report["status"] = "FAIL"
                        report["teardown_error"] = {"type": type(error).__name__, "message": str(error)}
                        if "error" not in report:
                            raise
                    else:
                        if report["process"]["exit_code"] != 0 or report["process"]["forced"] or report["process"]["cleanup_errors"]:
                            report["status"] = "FAIL"
        finally:
            try:
                receipts.close()
            except BaseException as error:
                report["status"] = "FAIL"
                report["capture_complete"] = False
                report["receipt_close_error"] = {"type": type(error).__name__, "message": str(error)}
                if "error" not in report:
                    raise
    except BaseException as error:
        report["status"] = "FAIL"
        report.setdefault("error", {"type": type(error).__name__, "message": str(error)})
        raise
    finally:
        report["caller_seconds"] = time.monotonic() - started
        print(json.dumps(report, ensure_ascii=False))
    if report["status"] != "PASS":
        raise RuntimeError("consumer did not complete normally")


if __name__ == "__main__":
    main()
