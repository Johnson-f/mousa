CREATE INDEX local_items_active_representation_idx
ON local_items(source_id, representation_id) WHERE active = 1;
