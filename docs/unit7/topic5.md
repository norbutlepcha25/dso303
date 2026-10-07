# Dijkstra's Algorithm

Dijkstra's Algorithm is one of the most famous and widely used algorithms in computer science. Developed by Dutch computer scientist Edsger W. Dijkstra in 1956, it solves the single-source shortest path problem for graphs with non-negative edge weights, finding the shortest paths from a starting node to all other nodes.

## 7.5.1 Single-source shortest path problem

The Single-Source Shortest Path (SSSP) problem is to find the shortest path from a given source vertex to all other vertices in a weighted graph.

Single-Source Shortest Path (SSSP): Finding the shortest paths from a single source node to all other nodes in a graph

Weighted Graph: A graph where edges have numerical weights (distances, costs, etc.)

Shortest Path: The path between two nodes with the minimum total edge weight

Relaxation: The process of updating the shortest distance to a node when a better path is found

**Problem Statement:**

Given:

- A graph 𝐺=(𝑉,𝐸)
- Each edge (𝑢,𝑣)∈𝐸 has a non-negative weight 𝑤(𝑢,𝑣)≥0
- A source vertex 𝑠 ∈ 𝑉

Goal:
Find the minimum distance from 𝑠 to every vertex 𝑣 ∈ 𝑉.

That is, compute: 𝑑[𝑣]= min (sum of weights along all paths from 𝑠 to 𝑣)

**Application**

| Domain                 | Use Case                                            |
| ---------------------- | --------------------------------------------------- |
| **Navigation Systems** | Google Maps, GPS routing                            |
| **Network Routing**    | OSPF (Open Shortest Path First) uses Dijkstra       |
| **Telecommunication**  | Finding least-cost paths in data networks           |
| **AI & Robotics**      | Pathfinding in games and robotic movement           |
| **Urban Planning**     | Optimal route planning for logistics and deliveries |
| **Flight Scheduling**  | Finding shortest (cheapest or fastest) flight paths |

!!! info "Fun fact"

    Dijkstra’s Algorithm was invented by Edsger W. Dijkstra in 1956 on a café napkin in 20 minutes!
    It’s one of the most influential algorithms in computer science.

## 7.5.2 Dijkstra's greedy strategy

Dijkstra’s Algorithm is a greedy algorithm because it always picks the vertex with the smallest known distance from the source and never reconsiders it.

Steps

- Start at the source vertex with distance 0.
- Repeatedly pick the unvisited vertex with the smallest tentative distance.
- Update (or relax) the distances of its neighboring vertices.
- Mark the vertex as visited (i.e., its shortest path is now finalized).
- Continue until all vertices are processed.

For each edge (u, v) with weight w(u, v):
If going through u gives a shorter path to v, then update it.

$$\text{if } d[v]>d[u]+w(u,v)⇒d[v]=d[u]+w(u,v)$$

!!! example "example"

{{image_block("../img/u7gdy/dji.jpg", "", "", "", size="large")}}

Given the weighted graph, calculate the minimum distance from point 1 to point 7
Using Table:

| Selected Node | 0                 | 1        | 2        | 3        | 4        | 5        | 6        | 7        |
| :------------ | :---------------- | :------- | :------- | :------- | :------- | :------- | :------- | :------- |
| 0             | $\textcircled{0}$ | $\infin$ | $\infin$ | $\infin$ | $\infin$ | $\infin$ | $\infin$ | $\infin$ |

Visit the next two nodes from node 0 : node 1 and node 2, and relax the nodes when necessary. Select the node with minimum distance and note it in selected node

| Selected Node | 0   | 1        | 2                 | 3        | 4        | 5        | 6        | 7        |
| :------------ | :-- | :------- | :---------------- | :------- | :------- | :------- | :------- | :------- |
| 0             |     | $\infin$ | $\infin$          | $\infin$ | $\infin$ | $\infin$ | $\infin$ | $\infin$ |
| 2             |     | 4        | $\textcircled{2}$ | $\infin$ | $\infin$ | $\infin$ | $\infin$ | $\infin$ |

Go to node 2 and visit the connected node from node 2. Select the node with shortest distance

| Selected Node | 0   | 1                 | 2                 | 3        | 4        | 5        | 6        | 7        |
| :------------ | :-- | :---------------- | :---------------- | :------- | :------- | :------- | :------- | :------- |
| 0             |     | $\infin$          | $\infin$          | $\infin$ | $\infin$ | $\infin$ | $\infin$ | $\infin$ |
| 2             |     | 4                 | $\textcircled{2}$ | $\infin$ | $\infin$ | $\infin$ | $\infin$ | $\infin$ |
| 1             |     | $\textcircled{4}$ |                   | $\infin$ | 10       | $\infin$ | $\infin$ | $\infin$ |

Continue until all the nodes are visited

| Selected Node | 0                 | 1                 | 2                 | 3                  | 4                 | 5                  | 6                 | 7                  |
| :------------ | :---------------- | :---------------- | :---------------- | :----------------- | :---------------- | :----------------- | :---------------- | :----------------- |
| 0             | $\textcircled{0}$ | $\infin$          | $\infin$          | $\infin$           | $\infin$          | $\infin$           | $\infin$          | $\infin$           |
| 2             |                   | 4                 | $\textcircled{2}$ | $\infin$           | $\infin$          | $\infin$           | $\infin$          | $\infin$           |
| 1             |                   | $\textcircled{4}$ |                   | $\infin$           | 10                | $\infin$           | $\infin$          | $\infin$           |
| 4             |                   |                   |                   | 10                 | $\textcircled{7}$ | $\infin$           | $\infin$          | $\infin$           |
| 6             |                   |                   |                   | 10                 |                   | $\infin$           | $\textcircled{9}$ | $\infin$           |
| 3             |                   |                   |                   | $\textcircled{10}$ |                   | $\infin$           |                   | 15                 |
| 7             |                   |                   |                   |                    |                   | 20                 |                   | $\textcircled{15}$ |
| 5             |                   |                   |                   |                    |                   | $\textcircled{20}$ |                   |                    |

## 7.5.3 Algorithm implementation and data structures

| Implementation            | Data Structure   | Time Complexity                           |
| ------------------------- | ---------------- | ----------------------------------------- |
| Simple array              | O(V²)            | For dense graphs                          |
| Min-Heap + Adjacency List | O((V + E) log V) | For sparse graphs (efficient)             |
| Fibonacci Heap            | O(E + V log V)   | Theoretical improvement, rare in practice |

## 7.5.4 Analysis and limitations of Dijkstra's algorithm

| Limitation                          | Explanation                                                                                                      |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| **No Negative Weights**             | Dijkstra assumes all edge weights ≥ 0. With negative edges, it can produce wrong results.                        |
| **Single Source Only**              | It finds shortest paths from one source; not all pairs (for that, we use Floyd–Warshall or Johnson’s algorithm). |
| **Not Suitable for Dynamic Graphs** | Must recompute if weights or edges change frequently.                                                            |
| **Can’t Handle Negative Cycles**    | Would cause infinite reduction in distance.                                                                      |
| **Higher Memory for Dense Graphs**  | O(V²) space if adjacency matrix is used.                                                                         |
