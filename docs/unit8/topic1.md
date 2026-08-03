# 7.1 Greedy Algorithm Design Principles

> Greedy algorithms are a fundamental class of algorithms that **build up a solution piece by piece**, always choosing the next piece that offers the **most immediate benefit (the locally optimal choice)**. They are widely used for optimization problems where local choices can lead to a globally optimal solution.

## 7.1.1 Characteristics of greedy algorithms

Greedy algorithms are defined by a specific approach to problem-solving:

1. **Myopic Decision-Making:** The algorithm makes a decision based only on the current information available. It does not look ahead to evaluate the long-term consequences of that decision.

2. **Irrevocability:** Once a choice is made, it is never reconsidered or undone. The solution is built incrementally and final.

3. **Sequence of Choices:** The solution is constructed through a sequence of choices, where each choice is made with the intent of being the best possible at that moment.

4. **Top-Down Approach:** A greedy strategy typically works in a top-down fashion, reducing each problem instance to a smaller one after each greedy choice.

Key Distinction from Dynamic Programming (DP):

Dynamic Programming: Makes decisions based on the solutions to all sub-problems. It is exhaustive and avoids re-computation by storing results. It's a "bottom-up" or "memoized" approach.

Greedy Algorithm: Makes one greedy choice after another, reducing the problem each time. It never reconsiders earlier choices. It's a "top-down" approach

## 7.1.2 Greedy choice property

This is the first of two essential properties a problem must have for a greedy algorithm to be optimal.

1. Definition: A problem exhibits the greedy choice property if a globally optimal solution can be arrived at by making a locally optimal (greedy) choice.

2. Implication: This property assures us that we can "guess" the first step of the solution correctly without having to solve all possible sub-problems first. We can make the choice that looks best right now, and then solve the remaining sub-problem.

Example - Activity Selection:

Problem: Select the maximum number of activities that don't overlap in time.

Greedy Choice: Always pick the next activity that finishes the earliest.

Why it works (Greedy Choice Property): This choice leaves the maximum amount of time available for future activities. If an optimal solution did not include the earliest-finishing activity, we could replace its first activity with the earliest-finishing one without causing any conflicts, proving that the greedy choice is part of some optimal solution.

## 7.1.3 Optimal substructure in greedy context

This is the second essential property, shared with Dynamic Programming.

Definition: A problem has optimal substructure if an optimal solution to the problem contains within it optimal solutions to its sub-problems.

In Greedy Algorithms: After making the first greedy choice, we are left with a smaller version of the original problem. The optimal substructure property guarantees that the solution to the overall problem is the combination of the greedy choice and the optimal solution to this remaining sub-problem.

Example - Activity Selection (Continued):

After we greedily select the activity A that finishes earliest, the remaining problem is to find the maximum set of non-overlapping activities from those that start after A finishes.

The optimal solution for the original problem is: [A] + (Optimal Solution for the sub-problem of activities starting after A finishes).

This recursive nature confirms the optimal substructure.

Summary of the Two Pillars:
For a greedy algorithm to yield a globally optimal solution:

Greedy Choice Property: We must be able to make the first best choice.

Optimal Substructure: The problem must break down into a smaller instance of itself after that choice.

## 7.1.4 Advantages and limitations of greedy approaches

Advantages:

Conceptual Simplicity: Greedy algorithms are often very intuitive and easy to conceptualize and describe.

Efficiency: They are typically very efficient, often running in linear or O(n log n) time (usually due to an initial sorting step). They avoid the complexity of solving all sub-problems, unlike DP.

Easy Implementation: The code for a greedy algorithm is usually straightforward and concise.

Limitations:

Not Always Optimal: The most significant drawback is that a greedy strategy does not work for every problem. It can easily get trapped in a local optimum, failing to find the true global optimum.

Classic Example: The Knapsack Problem. For the "0-1 Knapsack" problem (take the whole item or not), greedy on value/weight ratio is not optimal. However, for the "Fractional Knapsack" problem (can take parts of items), the same greedy strategy is optimal. This highlights that the problem's constraints are critical.

Difficulty in Proof: It can be very challenging to prove that a greedy algorithm will always yield the correct solution. This often requires rigorous mathematical proof using the greedy choice and optimal substructure properties.

Problem-Specific: A greedy strategy is highly tailored to a specific problem. There is no universal greedy template that can be applied to all problems.
