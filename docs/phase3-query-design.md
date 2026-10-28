# Phase 3 — Query Design

## 1. State Query
```
find_schemes_for_state("Karnataka")
```
Returns schemes with `APPLIES_TO_STATE → STATE:KARNATAKA` **plus** central schemes with `GLOBAL_APPLICABILITY → COUNTRY:INDIA`.

## 2. Crop Query
```
find_schemes_for_crop("ragi")
```
Returns schemes with `TARGETS_CROP → CROP:RAGI`.

## 3. State + Crop Query
```
find_schemes_for_state_and_crop("Karnataka", "ragi")
```
Returns: (state_schemes ∩ crop_schemes) ∪ global_crop_schemes.

## 4. Beneficiary Query
```
find_schemes_for_beneficiary("farmer")
```
Returns schemes with `TARGETS_BENEFICIARY → BENEFICIARY:FARMER`.

## 5. Profile Candidate Query
```
find_candidates_for_profile({
    "state": "Karnataka",
    "primary_crop": "ragi",
    "category": "OBC",
    "gender": "female",
    "occupation": "farmer"
})
```
Maps each categorical field to a graph node, finds connected schemes, returns `GraphCandidate` objects with match evidence and `graph_match_score`.

**This is NOT eligibility evaluation.** It is candidate discovery.

## 6. Neighbor Query
```
get_neighbors("SCHEME:PM_KISAN", relationship_type="TARGETS_CROP")
```
Returns typed neighbor info: node_id, relation, attributes.

## 7. Path Query
```
find_paths_between("STATE:KARNATAKA", "SCHEME:PM_KISAN", max_depth=2)
```
Returns short relationship paths (BFS, depth-limited for safety).

## GraphCandidate Result Model
```python
GraphCandidate:
    scheme_id: str
    scheme_name: str
    matched_relations: List[str]    # ["state", "crop", "category"]
    matched_nodes: List[str]        # ["Karnataka", "ragi", "OBC"]
    graph_match_score: int           # count of matched dimensions
    source_corpus_version: str
```
