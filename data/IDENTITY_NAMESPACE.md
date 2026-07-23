# Identifier namespace guard

The stable_old_id_3437 namespace and the reencoded_current_3437 namespace are distinct.

Direct OasisID joins between these namespaces are prohibited. A complete object-level join must consume all 117 rows in `oasis_id_crosswalk_117.csv`. The crosswalk is the only permitted bridge for stable-old attributes and current re-encoded geometries.

No geometry remapping or per-oasis base-value recomputation is performed in this archive.
