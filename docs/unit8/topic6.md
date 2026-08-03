# 7.6 Minimum Spanning Tree: Prim's and Kruskal's Algorithms

Minimum Spanning Tree (MST) is a fundamental graph theory problem with wide-ranging applications in network design, clustering, and optimization. Two classic algorithms—Prim's and Kruskal's—solve this problem efficiently using different greedy strategies.

## 7.6.1 Definition and applications of minimum spanning trees

A spanning tree of a connected, undirected, weighted graph 𝐺=(𝑉,𝐸) is a subset of edges 𝑇⊆𝐸 that:

1. Connects all vertices (spanning),
2. Contains no cycles (tree),
3. Has exactly ∣𝑉∣−1 edges.

A Minimum Spanning Tree (MST) is the spanning tree with the minimum possible total edge weight.
$$ Weight(𝑇)=\sum\_{(𝑢,𝑣)∈𝑇}𝑤(𝑢,𝑣) $$

and we want 𝑇 such that this sum is minimized.

**Application**

| Domain                       | Example                                                                        |
| ---------------------------- | ------------------------------------------------------------------------------ |
| **Network Design**           | Laying cables, pipelines, or fiber connections with minimal total cost.        |
| **Transportation**           | Designing railway, road, or airline routes to connect cities efficiently.      |
| **Electrical Circuits**      | Connecting electrical components using the least wiring.                       |
| **Image Processing**         | Segmenting images and clustering pixels using MST-based algorithms.            |
| **Approximation Algorithms** | Used in solving NP-hard problems like Travelling Salesman (TSP) approximation. |

## 7.6.2 Prim's algorithm: approach and analysis

Main idea: "Grow a tree from a starting vertex, always adding the cheapest edge connecting the tree to new vertices"

Algorithm Steps

1. Start with any vertex (say u).
2. Maintain a set MST for vertices included.
3. Choose the smallest edge that connects a vertex in MST to a vertex not in MST.
4. Add that edge and the vertex to MST.
5. Repeat until all vertices are included.

Visit this site to check an [Example](https://www.geeksforgeeks.org/dsa/prims-minimum-spanning-tree-mst-greedy-algo-5/)

Pseudo code

```
PRIM(G, w, r):      # G = (V, E), w = edge weights, r = start vertex
  for each vertex u in V:
      key[u] = ∞
      parent[u] = NIL
  key[r] = 0
  Q = set of all vertices

  while Q is not empty:
      u = vertex in Q with smallest key[u]
      remove u from Q

      for each vertex v adjacent to u:
          if v in Q and w(u, v) < key[v]:
              parent[v] = u
              key[v] = w(u, v)
```

| Data Structure                   | Time Complexity |
| -------------------------------- | --------------- |
| Adjacency matrix + simple search | ( O(V^2) )      |
| Min-Heap / Priority Queue        | ( O(E \log V) ) |

## 7.6.3 Kruskal's algorithm: approach and analysis

Main idea : "Sort all edges by weight and add them in increasing order, skipping edges that create cycles"

Steps:

1.  Sort all edges in increasing order of weight.
2.  Initialize MST as an empty set.
3.  For each edge (u, v) in sorted order:
4.  If adding (u, v) does not form a cycle (i.e., u and v belong to different sets):

    - Add it to MST.
    - Union the sets of u and v.

5.  Stop when MST has V – 1 edges.

Link for [Example](https://www.geeksforgeeks.org/dsa/kruskals-minimum-spanning-tree-algorithm-greedy-algo-2/)

Pseudo Code:

```
KRUSKAL(G):
  A = ∅
  for each vertex v in G.V:
      MAKE-SET(v)

  sort edges of G in non-decreasing order by weight

  for each edge (u, v) in sorted edges:
      if FIND-SET(u) ≠ FIND-SET(v):
          A = A ∪ {(u, v)}
          UNION(u, v)
  return A

```

Time Complexity: 𝑂(𝐸log𝐸)=𝑂(𝐸log𝑉)

## 7.6.4 Comparison of Prim's and Kruskal's algorithms

| Feature              | **Prim’s Algorithm**        | **Kruskal’s Algorithm**         |
| -------------------- | --------------------------- | ------------------------------- |
| **Approach**         | Vertex-based (grow tree)    | Edge-based (connect components) |
| **Data Structure**   | Priority Queue (Min-Heap)   | Disjoint Set (Union-Find)       |
| **Best for**         | Dense graphs (many edges)   | Sparse graphs (few edges)       |
| **Time Complexity**  | (O(E \log V))               | (O(E \log E))                   |
| **Cycle Handling**   | Automatically avoids cycles | Explicitly checks cycles        |
| **Implementation**   | Similar to Dijkstra         | Simpler conceptually            |
| **Example Use Case** | Network routing             | Cluster formation               |
