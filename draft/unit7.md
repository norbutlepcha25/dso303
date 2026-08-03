# Unit 7 Greedy Algorithm Design Principles

!!! info "Learning Outcome"

    1. Develop greedy algorithms for optimization problems, such as the fractional knapsack problem and activity selection.
    2. Examine the principles and applications of randomised algorithms in problem-solving.

---

> Greedy algorithms are a fundamental class of algorithms that **build up a solution piece by piece**, always choosing the next piece that offers the **most immediate benefit (the locally optimal choice)**. They are widely used for optimization problems where local choices can lead to a globally optimal solution.

## 7.1 Fundamental of Greedy Algorithm

### 7.1.1 Characteristics of greedy algorithms

Greedy algorithms follow a specific pattern in their design and implementation. The main characteristics include:

1. **Local Optimization:** At each step, the algorithm makes the choice that seems best at that moment (locally optimal decision).
2. **Irrevocability**: Once a choice is made, it cannot be changed later (no backtracking).
3. **Feasibility:** Each chosen step must lead to a valid intermediate solution (should not violate problem constraints).
4. **Greedy Criteria:** The algorithm selects the element with the maximum or minimum value according to a specific criterion.
5. **Iterative Construction:** The solution is built incrementally, step by step, until a complete solution is formed.

7.1.2 Greedy choice property
7.1.3 Optimal substructure in greedy context
7.1.4 Advantages and limitations of greedy approaches
