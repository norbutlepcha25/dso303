# Unit 7: Greedy Algorithms and Randomization

7.1 Greedy Algorithm Design Principles
7.1.1 Characteristics of greedy algorithms
7.1.2 Greedy choice property
7.1.3 Optimal substructure in greedy context
7.1.4 Advantages and limitations of greedy approaches
7.2 Fractional Knapsack Problem
7.2.1 Problem statement and comparison with 0/1 Knapsack
7.2.2 Greedy strategy for Fractional Knapsack
7.2.3 Proof of optimality
7.2.4 Time complexity and implementation considerations
7.3 Huffman Coding
7.3.1 Introduction to data compression
7.3.2 Huffman's greedy algorithm for optimal prefix codes
7.3.3 Building Huffman trees
7.3.4 Analysis of Huffman coding and its optimality
7.4 Activity Selection Problems
7.4.1 Problem formulation and real-world applications
7.4.2 Greedy approach to activity selection
7.4.3 Proof of correctness
7.4.4 Variations and extensions of the problem
7.5 Dijkstra's Algorithm
7.5.1 Single-source shortest path problem
7.5.2 Dijkstra's greedy strategy
7.5.3 Algorithm implementation and data structures
7.5.4 Analysis and limitations of Dijkstra's algorithm
7.6 Minimum Spanning Tree: Prim's and Kruskal's Algorithms
7.6.1 Definition and applications of minimum spanning trees
7.6.2 Prim's algorithm: approach and analysis
7.6.3 Kruskal's algorithm: approach and analysis
7.6.4 Comparison of Prim's and Kruskal's algorithms

## 7.7 Randomised Algorithms

> A randomized algorithm incorporates randomness as part of its logic. For the same input, its execution path, runtime, or even output might vary. It doesn’t produce the same output or take the same path every time, even for the same input.

### 7.7.1 Fundamentals of randomization in algorithm design

**Why Randomization in algorithms?**

1. **Simplicity:** Randomized algorithms are often much simpler to design and implement than the best known deterministic algorithms (e.g., Quicksort).

2. **Speed:** They can offer a significant performance improvement in practice and in expected worst-case time.

3. **Avoidance of Worst-Case Inputs:** By randomizing, we make the algorithm's performance independent of the specific input. An adversary cannot craft an input that guarantees worst-case behavior.

4. **Solving Difficult Problems:** For some problems, like primality testing, the best known practical solutions are randomized.

### 7.7.2 Las Vegas vs Monte Carlo algorithms

We classify randomized algorithms into two main types based on their output guarantees.

#### 7.7.2.1 Las Vagas Algorithm

Guarantee: Always correct. The output is guaranteed to be right.

Uncertainty: The running time is random.

Example: Randomized Quicksort. No matter what, it will always produce a correctly sorted array. However, its running time depends on the random choices of pivots.

#### 7.7.2.2 Monte Carlo algorithms

Guarantee: Always fast (has a bounded running time).

Uncertainty: The output has a random chance of being incorrect.

Example: Randomized Primality Testing (e.g., Fermat Test). It runs for a fixed number of iterations. If it says "composite," the number is definitely composite. If it says "prime," it might be wrong, but the probability of error can be made arbitrarily small.

| **Aspect**             | **Las Vegas Algorithms**                                | **Monte Carlo Algorithms**                                             |
| ---------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------- |
| **Output correctness** | Always correct                                          | May be incorrect                                                       |
| **Running time**       | Random (expected efficiency)                            | Deterministic or bounded                                               |
| **Example**            | Randomized Quicksort (always gives correct sorted list) | Randomized Primality Test (may incorrectly declare composite as prime) |
| **Error Type**         | None (but time varies)                                  | Probability of error (but time fixed)                                  |
| **Goal**               | Minimize expected runtime                               | Minimize error probability                                             |

7.7.3 Randomized Quicksort revisited
7.7.4 Randomized Primality Testing
7.7.5 Analysis techniques for randomized algorithms
