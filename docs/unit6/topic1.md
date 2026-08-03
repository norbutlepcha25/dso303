# 6.1 Dynamic Programming Design Principles

> Dynamic Programming (DP) is a problem-solving paradigm used for optimization problems where the solution can be built from solutions to overlapping subproblems. It combines recursion and memory optimization.

**Dynamic programming** is an algorithm design technique with a rather inter- esting history. It was invented by a prominent U.S mathematician, Richard Bellman, in the 1950s as a general method for optimizing multistage decision processes[^1].

## 6.1.1 Optimal substructure property

## 6.1.2 Overlapping subproblems

A problem exhibits overlapping subproblems if the same subproblems recur multiple times. Instead of recomputing, DP stores the results and reuses them.

Example:

<figure markdown="span">
    ![FST](../img/unit6_dp/fibtree.png){width="100%"}
    <figcaption>Fibonacci Sequence Tree</figcaption>
    <p align='right' style="font-size:0.8em"><i>Image Source: <a href="https://mathematica.stackexchange.com/questions/116344/how-do-i-create-a-recursive-tree-plot-for-the-fibonacci-sequence"> Stack Exchnage</a ></i></p>
</figure>

Fibonacci sequence (recursive) repeatedly solves the same subproblems (e.g., Fib(3) is computed multiple times).
Using DP, we compute each Fibonacci number once and store it.

## 6.1.3 Memoization vs tabulation approaches

**Memoization (Top-Down):** Recursive calling + caching results i.e., Compute on demand and store results.Easier to implement if recursion is natural.

**Tabulation Approch(Bottom-up approch)**: Stores the results of subproblems in a table
Iterative implementation. Entries are filled in a bottom-up manner from the smallest size to the final size.

## Reference

[^1]: **_Introduction to the Design and Analysis of Algorithms_** by Anany Levitin
