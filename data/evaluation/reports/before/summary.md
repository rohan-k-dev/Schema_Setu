# SchemeSetu evaluation — before

- Generated: 2026-10-13T17:29:17.200383+00:00
- Mode: offline
- App 0.6.0 · corpus 1.0.0 · graph 1.0.0 · engine 1.0.0
- Commit: a95ab12 (dirty working tree: True)

## Scorecard

| Category | Metric | Target | Actual | Status |
|---|---|---|---|---|
| Profile | Deterministic profile-layer scenarios pass rate | >= 1 | 0.3636 | FAIL |
| Profile | LLM extraction field F1 (live) | >= 0.9 | — | NOT_MEASURED |
| Retrieval | Merged targeted recall@10 | >= 0.9 | 0.25 | FAIL |
| Retrieval | Merged precision@10 (applicable schemes) | >= 1 | 1 | PASS |
| Retrieval | DB targeted recall@10 | >= 0.9 | 0.25 | FAIL |
| Retrieval | Graph false relationships (out-of-scope schemes) | <= 0 | 13 | FAIL |
| Retrieval | Graph crop-filter accuracy | >= 1 | 0.35 | FAIL |
| Retrieval | Exact lookup / adversarial query pass rate | >= 1 | 0.9 | PARTIAL |
| Retrieval | Candidate merge correctness | >= 1 | 0.8 | PARTIAL |
| Retrieval | Source-conflict handling | >= 1 | 1 | PASS |
| Retrieval | Failure matrix (6 combinations) | >= 1 | 0 | FAIL |
| Retrieval | Tavily pipeline (URL kept, official linked, unrelated dropped) | >= 1 | 0.3333 | FAIL |
| Retrieval | Parallel retrieval (2s+1s+3s mocked) seconds | <= 4 | 3.021 | PASS |
| Eligibility | Scheme-level accuracy | >= 1 | 0.9615 | PARTIAL |
| Eligibility | Rule-level accuracy | >= 1 | 1 | PASS |
| Eligibility | False-positive rate (ELIGIBLE when gold NOT_ELIGIBLE) | <= 0 | 0.0286 | FAIL |
| Eligibility | False-negative rate | <= 0 | 0.0204 | FAIL |
| Eligibility | Operator coverage probes | >= 1 | 1 | PASS |
| Eligibility | Three-valued logic truth table | >= 1 | 1 | PASS |
| Eligibility | Rule provenance (source text + URL + version) | >= 1 | 0 | FAIL |
| Eligibility | Determinism (same input -> same result) | >= 1 | 1 | PASS |
| Eligibility | UNKNOWNs caused by unsupported profile fields | info | 59 | INFO |
| Eligibility | NEEDS_MORE_INFORMATION rate (fully stated profiles) | info | 0.295 | INFO |
| Eligibility | UNVERIFIABLE rate (corpus rule coverage) | info | 0.45 | INFO |
| XAI | Status consistency | >= 1 | 0.9375 | PARTIAL |
| XAI | Supported-claim grounding | >= 1 | 1 | PASS |
| XAI | Numeric grounding | >= 1 | 1 | PASS |
| XAI | URL grounding | >= 1 | 1 | PASS |
| XAI | Genuine explanations accepted by validator | >= 1 | 0.9688 | PARTIAL |
| XAI | Fabrication probes rejected | >= 1 | 0.2031 | FAIL |
| XAI | Official source cited when available | >= 1 | 0 | FAIL |
| Recommendation | Ranking checks | >= 1 | 0.4286 | FAIL |
| Multilingual | Profile parity across languages (offline) | >= 1 | 1 | PASS |
| Multilingual | Eligibility parity across languages (offline) | >= 1 | 1 | PASS |
| Multilingual | XAI evidence parity (offline) | >= 1 | 1 | PASS |
| Multilingual | Translation is presentation-only | >= 1 | 1 | PASS |
| Multilingual | Translation-failure fallback | >= 1 | 1 | PASS |
| Multilingual | Live Sarvam translation quality | >= — | — | NOT_MEASURED |
| Voice | Post-ASR pipeline (mocked ASR) | >= 1 | 0.875 | PARTIAL |
| Voice | Voice/text session continuity | >= 1 | 0.5 | FAIL |
| Voice | Failure fallbacks + upload security | >= 1 | 0.9 | PARTIAL |
| Voice | Word error rate (real audio) | <= — | — | NOT_MEASURED |
| Human Review | HITL checks (escalation, lifecycle, audit, privacy, auth) | >= 1 | 0.9545 | PARTIAL |
| Security | Red-team probes passed | >= 1 | 0.4722 | FAIL |
| End-to-end | Golden journeys passed | >= 1 | 0.3333 | FAIL |
| Performance | Offline text request P95 (ms, external services mocked) | <= 2000 | 393.5 | PASS |
| Performance | Offline voice round trip P95 (ms, mocked ASR/TTS) | <= 3000 | 539.7 | PASS |
| Performance | Review-II live latency target 10-15 s | <= 15000 | — | NOT_MEASURED |
| Performance | Concurrent load error rate (200 req, c=10) | <= 0 | 0 | PASS |
| Performance | Concurrent load P95 (ms) | <= 5000 | 1.182e+04 | FAIL |
| Stability | Graph reloads during run | <= 0 | 0 | PASS |
| Stability | RSS growth over last 100 requests at session cap (KB) | <= 10240 | — | NOT_MEASURED |
| Stability | Soak test errors | <= 0 | — | NOT_MEASURED |
| Accessibility | Static accessibility audit checks | >= 1 | 0.6923 | FAIL |
| User Study | Task completion rate | >= — | — | NOT_MEASURED |
| Expert Validation | Outputs rated CORRECT | >= — | — | NOT_MEASURED |

Status counts: FAIL=18, INFO=3, NOT_MEASURED=8, PARTIAL=8, PASS=19

## Failing checks (first 15 per area)

### profile
- `PL04` — {"area": "completeness", "failures": ["question targets ['land_size_acres'], expected state (reply='Could you please tell me more about your farming land?')"]}
- `PL06` — {"area": "completeness", "failures": ["question targets ['land_size_acres'], expected primary_crop (reply='Could you please tell me more about your farming land?')"]}
- `PL08` — {"area": "invalid_value", "failures": ["profile.land_size_acres should be absent, got -5.0", "question targets [], expected land_size_acres (reply='\\n4 scheme(s) may match but need more information:\\n\\n• **Dairy Entrepreneurship De')"]}
- `PL11` — {"area": "question", "failures": ["question sequence ['land_size_acres', 'land_size_acres'] expected ['state', 'land_size_acres']", "duplicate question asked"]}
- `PL12` — {"area": "normalization", "failures": ["profile.state='karnataka' expected 'Karnataka'"]}
- `PL13` — {"area": "normalization", "failures": ["profile.state='KA' expected 'Karnataka'"]}
- `PL14` — {"area": "normalization", "failures": ["profile.primary_crop='paddy' expected 'rice'"]}
- `PL15` — {"area": "normalization", "failures": ["profile.category='scheduled caste' expected 'SC'"]}
- `PL16` — {"area": "normalization", "failures": ["profile.gender='woman' expected 'female'", "profile.occupation=None expected 'farmer'"]}
- `PL17` — {"area": "fields", "failures": ["profile.occupation=None expected 'farmer'"]}
- `PL18` — {"area": "fields", "failures": ["profile.age=None expected 35"]}
- `PL19` — {"area": "invalid_value", "failures": ["profile.annual_income should be absent, got nan"]}
- `PL20` — {"area": "follow_up", "failures": ["referenced_scheme_id=None expected 'KCC'"]}
- `PL21` — {"area": "ambiguity", "failures": ["status=partial_results expected clarification_required"]}

### retrieval
- `L06` — {"returned": ["AGMARKNET", "AGRI_INFRA_FUND", "ATMA", "DEDS", "FPO_SCHEME"], "crashed": false, "query_len": 0}
- `M03` — {"ids": ["KUSUM", "PM_KUSUM"], "sources": {"PM_KUSUM": ["DATABASE", "KNOWLEDGE_GRAPH"], "KUSUM": ["LIVE_WEB"]}}
- `F01` — {"expected_errors": ["live_web"], "reported_errors": [], "candidate_sources": ["DATABASE", "KNOWLEDGE_GRAPH"], "candidates": 10}
- `F02` — {"expected_errors": ["knowledge_graph"], "reported_errors": [], "candidate_sources": ["DATABASE", "LIVE_WEB"], "candidates": 10}
- `F03` — {"expected_errors": ["database"], "reported_errors": [], "candidate_sources": ["KNOWLEDGE_GRAPH", "LIVE_WEB"], "candidates": 10}
- `F04` — {"expected_errors": ["knowledge_graph", "live_web"], "reported_errors": [], "candidate_sources": ["DATABASE"], "candidates": 10}
- `F05` — {"expected_errors": ["database", "knowledge_graph"], "reported_errors": [], "candidate_sources": ["LIVE_WEB"], "candidates": 2}
- `F06` — {"expected_errors": ["database", "knowledge_graph", "live_web"], "reported_errors": [], "candidate_sources": [], "candidates": 0}
- `url_preserved` — {}
- `known_scheme_linked` — {}

### eligibility
- `E26` — {"dataset": "eligibility_v1", "expected": "ELIGIBLE", "actual": "NOT_ELIGIBLE"}
- `CE01` — {"dataset": "corpus_eligibility_v1", "expected": "ELIGIBLE", "actual": "NEEDS_MORE_INFORMATION"}
- `CE02` — {"dataset": "corpus_eligibility_v1", "expected": "NOT_ELIGIBLE", "actual": "NEEDS_MORE_INFORMATION"}
- `N08` — {"dataset": "eligibility_logic_v1", "expected": "NOT_ELIGIBLE", "actual": "ELIGIBLE"}
- `DEDS:rule0` — {"has_source_text": true, "source_url": null, "expected_url": "https://dahd.nic.in", "corpus_version": "1.0.0"}
- `DEDS:rule1` — {"has_source_text": true, "source_url": null, "expected_url": "https://dahd.nic.in", "corpus_version": "1.0.0"}
- `KCC:rule0` — {"has_source_text": true, "source_url": null, "expected_url": "https://www.myscheme.gov.in/schemes/kcc", "corpus_version": "1.0.0"}
- `MGNREGA:rule0` — {"has_source_text": true, "source_url": null, "expected_url": "https://nrega.nic.in", "corpus_version": "1.0.0"}
- `MKSP:rule0` — {"has_source_text": true, "source_url": null, "expected_url": "https://nrlm.gov.in", "corpus_version": "1.0.0"}
- `MOVCDNER:rule0` — {"has_source_text": true, "source_url": null, "expected_url": "https://agricoop.nic.in", "corpus_version": "1.0.0"}
- `NMOOP:rule0` — {"has_source_text": true, "source_url": null, "expected_url": "https://agricoop.nic.in", "corpus_version": "1.0.0"}
- `PKVY:rule0` — {"has_source_text": true, "source_url": null, "expected_url": "https://pgsindia-ncof.gov.in/pkvy/index.aspx", "corpus_version": "1.0.0"}
- `PMFBY:rule0` — {"has_source_text": true, "source_url": null, "expected_url": "https://pmfby.gov.in", "corpus_version": "1.0.0"}
- `PMJJBY:rule0` — {"has_source_text": true, "source_url": null, "expected_url": "https://jansuraksha.gov.in", "corpus_version": "1.0.0"}
- `PMKSY:rule0` — {"has_source_text": true, "source_url": null, "expected_url": "https://pmksy.gov.in", "corpus_version": "1.0.0"}

### xai
- `X21` — {"expected": "ELIGIBLE", "actual": "NEEDS_MORE_INFORMATION"}
- `X22` — {"expected": "NOT_ELIGIBLE", "actual": "NEEDS_MORE_INFORMATION"}
- `X18` — {}
- `X01:new_threshold` — {"probe": "new_threshold"}
- `X01:new_url` — {"probe": "new_url"}
- `X01:new_rule` — {"probe": "new_rule"}
- `X02:new_threshold` — {"probe": "new_threshold"}
- `X02:new_url` — {"probe": "new_url"}
- `X02:new_rule` — {"probe": "new_rule"}
- `X03:new_threshold` — {"probe": "new_threshold"}
- `X03:new_url` — {"probe": "new_url"}
- `X03:new_rule` — {"probe": "new_rule"}
- `X04:claim_eligible` — {"probe": "claim_eligible"}
- `X04:new_threshold` — {"probe": "new_threshold"}
- `X04:new_url` — {"probe": "new_url"}

### recommendation
- `ORDER_INDEPENDENT_TIES` — {"distinct_orders": 6}
- `GRAPH_EVIDENCE_USED` — {"reasons": ["2 criteria matched", "All available criteria verified"]}
- `EVIDENCE_FIELDS_PRESENT` — {"missing_keys": ["graph_evidence", "official_url", "sources"], "schemes": 10}
- `GRAPH_EVIDENCE_IN_RESPONSE` — {"schemes_with_graph_evidence": 0}

### voice
- `V05` — {"language": "hi", "failures": ["occupation=None expected 'farmer'"]}
- `V09` — {"language": "ta", "failures": ["primary_crop='paddy' expected 'rice'"]}
- `VS2` — {"failures": ["occupation=None expected 'farmer'"]}
- `VF08` — {"kind": "malformed_audio", "error": "VOICE_TRANSCRIPTION_FAILED", "asr_calls": 1}

### human_review
- `ESC_UNVERIFIABLE` — {"expected": "UNVERIFIABLE", "actual": null, "area": "escalation"}

### adversarial
- `A01` — {"category": "PROFILE", "kind": "profile_value", "attack": "Negative land size", "stored": {"land_size_acres": -5.0}}
- `A03` — {"category": "PROFILE", "kind": "profile_value", "attack": "NaN land", "stored": {"land_size_acres": NaN}}
- `A04` — {"category": "PROFILE", "kind": "profile_value", "attack": "Infinite income", "stored": {"annual_income": Infinity}}
- `A05` — {"category": "PROFILE", "kind": "profile_value", "attack": "Non-existent state", "stored": {"state": "Xyzland"}}
- `A06` — {"category": "PROFILE", "kind": "profile_value", "attack": "SQL text in a profile field", "stored": {"state": "Karnataka'; DROP TABLE schemes;--"}}
- `A07` — {"category": "PROFILE", "kind": "profile_value", "attack": "Negative income", "stored": {"annual_income": -150000.0}}
- `A08` — {"category": "ELIGIBILITY", "kind": "engine_numeric", "attack": "Negative land as a string must not pass a <= rule", "status": "ELIGIBLE"}
- `A09` — {"category": "ELIGIBILITY", "kind": "engine_numeric", "attack": "NaN income must be unknown, not a decision", "status": "NOT_ELIGIBLE"}
- `A10` — {"category": "ELIGIBILITY", "kind": "engine_numeric", "attack": "Plural 'lakhs' notation", "status": "NEEDS_MORE_INFORMATION"}
- `A13` — {"category": "XAI", "kind": "formatter_fabrication", "attack": "§101 LLM claims eligibility the engine denied", "llm_reply_used": true}
- `A14` — {"category": "XAI", "kind": "formatter_fabrication", "attack": "§103 URL fabrication", "llm_reply_used": true}
- `A15` — {"category": "XAI", "kind": "formatter_fabrication", "attack": "§104 number fabrication", "llm_reply_used": true}
- `A16` — {"category": "XAI", "kind": "formatter_fabrication", "attack": "§105 scheme fabrication", "llm_reply_used": true}
- `A18` — {"category": "SECURITY", "kind": "static_sql_scan", "attack": "§106 SQL injection", "interpolated_sql": ["backend\\app\\services\\corpus_import_service.py:307: await cur.execute(f\"DELETE FROM {table} WHERE scheme_id = %s\", (db_id,))"]}
- `A25` — {"category": "VOICE", "kind": "audio_upload", "attack": "§109 malformed audio", "error": "VOICE_TRANSCRIPTION_FAILED", "asr_calls": 1}

### e2e
- `E2E01` — {"title": "Simple eligible farmer", "failures": ["STATE_KA_KRUSHAK not returned", "PM_KISAN not returned", "STATE_KA_KRUSHAK status=None expected ELIGIBLE", "PM_KISAN status=None expected ELIGIBLE"], "final_status": "schemes_found"}
- `E2E02` — {"title": "Ineligible farmer (land above limit)", "failures": ["PM_KMY not returned", "PM_KMY status=None expected NOT_ELIGIBLE"], "final_status": "schemes_found"}
- `E2E03` — {"title": "Missing information (age)", "failures": ["PM_KMY not returned", "PM_KMY status=None expected NEEDS_MORE_INFORMATION", "PM_KMY missing_information=[] expected ⊇ ['age']"], "final_status": "schemes_found"}
- `E2E06` — {"title": "State + crop match", "failures": ["STATE_AP_RYTHU not returned", "NMOOP not returned", "STATE_AP_RYTHU status=None expected ELIGIBLE", "NMOOP status=None expected ELIGIBLE"], "final_status": "schemes_found"}
- `E2E07` — {"title": "Category-specific (optional category rule)", "failures": ["DEDS status=NEEDS_MORE_INFORMATION expected ELIGIBLE"], "final_status": "schemes_found"}
- `E2E10` — {"title": "Aadhaar requirement visible in documents", "failures": ["PM_KISAN not returned", "PM_KISAN documents=[] expected ⊇ ['Aadhaar Card', 'Land Records']", "PM_KISAN has no application steps", "PM_KISAN has no source URL"], "final_status": "schemes_found"}
- `E2E11` — {"title": "Multiple AND rules (PM-KMY eligible)", "failures": ["PM_KMY not returned", "STATE_UP_KISAN not returned", "NFSM not returned", "PM_KMY status=None expected ELIGIBLE", "STATE_UP_KISAN status=None expected ELIGIBLE"], "final_status": "schemes_found"}
- `E2E12` — {"title": "Landless farmer (has_land FAIL)", "failures": ["PM_KISAN not returned", "PM_KISAN status=None expected NOT_ELIGIBLE"], "final_status": "schemes_found"}
- `E2E13` — {"title": "Follow-up scheme question", "failures": ["follow-up referenced None / returned ['DEDS', 'KCC'] expected first of ['KCC', 'DEDS', 'MGNREGA']"], "final_status": "partial_results"}
- `E2E14` — {"title": "Voice input", "failures": ["STATE_KA_KRUSHAK status=None expected ELIGIBLE"], "final_status": "schemes_found"}
- `E2E15` — {"title": "Multilingual input (Hindi)", "failures": ["STATE_KA_KRUSHAK status=None expected ELIGIBLE", "PM_KISAN status=None expected ELIGIBLE"], "final_status": "schemes_found"}
- `E2E17` — {"title": "Tavily failure", "failures": ["STATE_KA_KRUSHAK not returned", "STATE_KA_KRUSHAK status=None expected ELIGIBLE", "retrieval error for live_web not reported (errors=[])"], "final_status": "partial_results"}
- `E2E18` — {"title": "Knowledge Graph failure", "failures": ["STATE_KA_KRUSHAK not returned", "retrieval error for knowledge_graph not reported (errors=[])"], "final_status": "partial_results"}
- `E2E19` — {"title": "Database failure (no false eligibility)", "failures": ["retrieval error for database not reported (errors=[])"], "final_status": "partial_results"}
- `E2E20` — {"title": "Human-review escalation", "failures": ["no human-review case created for the session"], "final_status": "schemes_found"}

### accessibility
- `HTML_LANG_FOLLOWS_SELECTED_LANGUAGE` — {"note": "screen readers need <html lang> to match the chosen language"}
- `TOUCH_TARGETS_44PX` — {"below_44px": ["components\\SchemeList.tsx"], "unsized": []}
- `VISIBLE_FOCUS_STYLES` — {"count": 2}
- `AUDIO_PLAYBACK_CAN_BE_STOPPED` — {"note": "TTS audio should be stoppable by the user"}

