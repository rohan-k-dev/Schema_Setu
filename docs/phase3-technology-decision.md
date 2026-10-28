# Phase 3 Technology Decision — NetworkX

## Decision
Use **Python + NetworkX** (`networkx.MultiDiGraph`) for the initial Knowledge Graph.

## Rationale
1. **Native Python integration** — no additional server infrastructure
2. **Easy to test** — in-memory graph, no DB required for graph tests
3. **No additional server** — no Neo4j, Redis, or external service
4. **Direct from PostgreSQL** — built via repositories, not raw SQL
5. **Supports directed multi-relational edges** — `MultiDiGraph`
6. **Graph traversal** — BFS, shortest paths, neighbor queries
7. **Suitable for academic prototype** — well-documented, widely used
8. **Simple deployment** — just a Python dependency
9. **Future migration path** — can migrate to Neo4j when needed

## Future Migration
| Current | Future |
|---------|--------|
| NetworkX in-process | Neo4j / dedicated graph DB |
| JSON snapshots | Graph database persistence |
| In-memory graph | Distributed graph |

The `KnowledgeGraphRepository` interface hides NetworkX specifics, making migration easier.

## Alternatives Considered
- **Neo4j**: Too heavy for Phase 3 prototype; requires additional server
- **RDFLib**: More complex, SPARQL learning curve
- **igraph**: Less Python-native API
- **Custom dict-based**: Not a real graph; no traversal algorithms
