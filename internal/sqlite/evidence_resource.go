package sqlite

import (
	"context"
	"database/sql"
	"errors"

	"github.com/graydeon/mousa/internal/mousa"
)

// EvidenceResource is a fresh authorization and an active, verified passage.
// A denied, unscoped or retired passage never releases evidence or its existence.
type EvidenceResource struct {
	Schema     string                   `json:"schema"`
	DecisionID mousa.PolicyDecisionID   `json:"decision_id"`
	Evidence   *evidenceResourcePassage `json:"evidence,omitempty"`
}

type evidenceResourcePassage struct {
	Segment mousa.Segment          `json:"segment"`
	Text    string                 `json:"text"`
	Paths   []evidenceResourcePath `json:"paths"`
}

type evidenceResourcePath struct {
	RepresentationIDs []mousa.RepresentationID `json:"representation_ids"`
	ArtifactID        mousa.ArtifactID         `json:"artifact_id"`
	ObservationID     mousa.ObservationID      `json:"observation_id"`
	SourceID          mousa.SourceID           `json:"source_id"`
}

// ReadEvidenceResource evaluates source policy and checks canonical ancestry,
// content and lifecycle in the same writer snapshot before releasing text.
func (store *Store) ReadEvidenceResource(ctx context.Context, request mousa.PolicyEvaluationRequest, id mousa.SegmentID) (EvidenceResource, error) {
	if err := store.requireWritable("read evidence resource"); err != nil {
		return EvidenceResource{}, err
	}
	if err := request.Validate(); err != nil {
		return EvidenceResource{}, wrap(CodeInvalidRecord, "read evidence resource", err)
	}
	if id == (mousa.SegmentID{}) {
		return EvidenceResource{}, wrap(CodeInvalidRecord, "read evidence resource", errors.New("segment ID must not be zero"))
	}
	result := EvidenceResource{Schema: "mousa.evidence_resource.v1"}
	err := store.writeImmediate(ctx, "read evidence resource", func(conn *sql.Conn) error {
		decision, err := evaluateSourceRetrieval(ctx, conn, request, false)
		if err != nil {
			return err
		}
		result.DecisionID = decision.ID
		if decision.Outcome != mousa.PolicyOutcomeAllow {
			return nil
		}
		raw, err := queryLexicalCandidates(ctx, conn, `SELECT r.segment_id, f.text, f.content_sha256, 0.0 FROM segment_lexical_rows AS r JOIN segment_lexical_fts AS f ON f.rowid = r.rowid WHERE r.segment_id = ?`, id[:])
		if err != nil {
			return err
		}
		if len(raw) == 0 {
			return nil
		}
		verified, err := verifyLexicalEvidence(ctx, conn, raw)
		if err != nil {
			return err
		}
		candidate := verified[0]
		if candidate.Disposition != mousa.CandidateAccepted {
			return nil
		}
		// Verification considers every derivation's restrictive lifecycle, but
		// this release projects only the newly authorized source's ancestry.
		paths := make([]evidenceResourcePath, 0, len(candidate.Paths))
		for _, path := range candidate.Paths {
			if path.SourceID == request.SourceID {
				paths = append(paths, evidenceResourcePath{RepresentationIDs: path.RepresentationIDs, ArtifactID: path.ArtifactID, ObservationID: path.ObservationID, SourceID: path.SourceID})
			}
		}
		if len(paths) == 0 {
			return nil
		}
		if len(candidate.Text) > 65536 {
			return wrap(CodeResourceLimit, "read evidence resource", errors.New("passage exceeds 65536 bytes"))
		}
		result.Evidence = &evidenceResourcePassage{Segment: candidate.Segment, Text: candidate.Text, Paths: paths}
		return nil
	})
	return result, err
}
