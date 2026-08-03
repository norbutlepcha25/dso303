# 3.1 Recurrences & Master Theorem (Analysis)

## 3.1.1 Introduction to recurrence relations

A recurrence is an equation (or inequality) that defines a function in terms of its value(s) at smaller input(s).It’s a way of expressing a problem’s solution in terms of **_smaller subproblems_** of the same type. In simple terms, we can say that when a function calls itself within that function, only the parameter are different, which is usally the smaller sub problem.

A **recurrence relation** is an {== equation that defines a sequence based on its previous terms ==}. A recurrence relation is the actual formula that shows how the current value depends on previous values.

For example:

Factorial recurrence:
$ T(𝑛)=𝑛.T(𝑛-1), T(0)=1 $

This means factorial of 𝑛 is defined in terms of factorial of 𝑛−1.

\[
T(n) = a \cdot T\!\left(\frac{n}{b}\right) + f(n)
\]

Where:

- \(T(n)\) → the time/space complexity of the problem of size \(n\)
- \(a\) → number of subproblems in the recursion
- \(n/b\) → size of each subproblem
- \(f(n)\) → the cost of dividing the problem and combining the results

---

## 3.1.2 Types of recurrences

1.  **Linear Recurrence** – depends linearly on smaller subproblems.
    Example: $T(n) = T(n-1) + O(1)$
2.  **Divide-and-Conquer Recurrence** – splits into multiple subproblems.
    Example: $T(n) = aT(\frac{n}{b}) + f(n)$

    - Homogeneous: depends only on subproblems ($T(n) = 2T(\frac{n}{2})$).
    - Non-Homogeneous: includes an additional function ($T(n) = 2T(\frac{n}{2}) + n$).

## 3.1.3 Overview of the Master Theorem

When analyzing recursive algorithms, we use different techniques to solve **recurrence relations** and find their {==closed-form or asymptotic complexity==}.  
Here are the main methods:

1. Iterative Method
2. Recursion tree
3. Substitution Method
4. Telescoping
5. Master theorem

## reference

## Test Your self
