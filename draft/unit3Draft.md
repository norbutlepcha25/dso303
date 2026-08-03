## 2. Recursion Tree Method

- Represent the recurrence as a **tree of recursive calls**.
- Each level of the tree corresponds to one stage of recursion.
- Calculate the total cost by summing work done at each level.
- Helps visualize how cost is distributed across recursive calls.
- **Example:** Merge Sort recurrence forms a balanced binary tree.

---

## 3. Substitution Method (Induction Method)

- Guess the solution (closed-form or Big-O).
- Use **mathematical induction** to prove the guess is correct.
- Commonly used for formal correctness proofs.
- **Example:**  
  Guess \(T(n) = O(n \log n)\) for Merge Sort, then prove by induction.

---

## 4. Telescoping (Backward Substitution)

- Special form of the iterative method where terms **cancel out** when expanded.
- Works best when recurrence has differences between consecutive terms.
- **Example:**  
  \[
  T(n) = T(n-1) + \frac{1}{n}
  \]  
  Expands into a **harmonic series** that telescopes.

---

## 5. Master Theorem

- A direct formula to solve **divide and conquer** recurrences:  
  \[
  T(n) = a \cdot T\!\left(\frac{n}{b}\right) + f(n)
  \]
- Provides asymptotic complexity based on comparison of \(f(n)\) with \(n^{\log_b a}\).
- Three main cases:
  - Case 1: \(f(n)\) grows slower → \(T(n) = \Theta(n^{\log_b a})\)
  - Case 2: \(f(n)\) grows equally → \(T(n) = \Theta(n^{\log_b a} \cdot \log n)\)
  - Case 3: \(f(n)\) grows faster → \(T(n) = \Theta(f(n))\) (with regularity condition)

---

## Summary

- **Iterative Method** → Expand step by step.
- **Recursion Tree** → Visualize and sum across levels.
- **Substitution Method** → Guess and prove with induction.
- **Telescoping** → Cancel terms to simplify.
- **Master Theorem** → Direct formula for divide & conquer recurrences.

<!-- Need to add in the master theorem part -->

---

## 3. CLRS Master Theorem (Extended Form)

**Definition:**  
CLRS expresses the Master Theorem using:

\[
f(n) = \Theta(n^k \log^p n)
\]  
and compares constants \(a\) and \(b^k\):

- \(a < b^k\) → outside work dominates → \(T(n) = \Theta(n^k \log^p n)\)
- \(a = b^k\) → balanced → \(T(n) = \Theta(n^k \log^{p+1} n)\)
- \(a > b^k\) → recursion dominates → \(T(n) = \Theta(n^{\log_b a})\)

**Meaning:**

- CLRS version is basically the **Extended Master Theorem**.
- \(p\) accounts for logarithmic factors in \(f(n)\).
- Makes comparison easier by comparing **constants** instead of functions.

---

## 4. Related Concepts

### 4.1 Big-O, Big-Theta, Big-Omega

- **Big-O (O)** → Upper bound: algorithm grows **at most** this fast
- **Big-Theta (Θ)** → Tight bound: algorithm grows **exactly** this fast
- **Big-Omega (Ω)** → Lower bound: algorithm grows **at least** this fast

### 4.2 Floor and Ceiling

- **Floor ⌊x⌋** → largest integer ≤ x
- **Ceiling ⌈x⌉** → smallest integer ≥ x
- Used in recurrences to ensure **integer subproblem sizes**

### 4.3 Why Multiple Methods?

- Master Theorem works for \(T(n) = aT(n/b) + f(n)\) with nice \(f(n)\)
- **Other methods** (Recursion Tree, Substitution, Iteration, Akra-Bazzi) are needed when:
  - Non-polynomial \(f(n)\)
  - Non-uniform splits (e.g., \(T(n/2) + T(n/3) + n\))
  - Linear reductions (e.g., \(T(n-1) + n\))

---

**Summary:**

- **Classic Master Theorem:** simple polynomial \(f(n)\)
- **Extended / CLRS Master Theorem:** handles \(f(n) = n^k \log^p n\)
- Use **Big-O / Θ / Ω** to compare recursive vs non-recursive work
- Use **floor/ceiling** to handle integer sizes

## Additional Resources

1. Strassen's Algorithm

   -[Youtube Video 1](https://www.youtube.com/watch?v=OSelhO6Qnlc){:target="\_blank"}
