# 5.2 Lower Bound for Sorting

> A lower bound is the best possible (minimum) time complexity that any algorithm of a certain type can achieve for a given problem.

All comparison-based sorting algorithms (like Merge Sort, Quick Sort, Heap Sort, etc.) decide the order of elements by comparing pairs of elements (using <, >). Every sorting process can be seen as a series of decisions — each comparison narrows down the possible orderings of the input.

## 5.2.1 Decision tree model for comparison-based sorting

<figure markdown="span">
    ![DT](../img/unit5Sorting/decisionTree.png){width="60%"}
    <figcaption>Example of a decision Tree</figcaption>
    <p align='right' style="font-size:0.8em"><i>Image Source: <a href="https://www.comp.nus.edu.sg/~stevenha/cs3230/lectures/lec04a.pdf" target="_blank"> NUS Notes</a ></i></p>
</figure>

A decision tree is a rooted tree

- Start from the root.
- At every node, a question is asked.
- Depending on the answer, a child is chosen.
- At a leaf, a decision is taken.

Similarly any comparison-based algorithm can be modeled using a decision tree:

- Internal Nodes: Represent a comparison between two elements (e.g., aᵢ ≤ aⱼ?).
- Branches: Represent the outcome of the comparison (Yes/No).
- Leaves: Represent one of the possible n! permutations of the input. A correct sorting algorithm must have a unique leaf for each permutation.

<figure markdown="span">
    ![DT](../img/unit5Sorting/exampleDTSA.png){width="80%"}
    <figcaption>Example of a decision Tree</figcaption>
    <p align='right' style="font-size:0.8em"><i>Image Source: <a href="https://www.comp.nus.edu.sg/~stevenha/cs3230/lectures/lec04a.pdf" target="_blank"> NUS Notes</a ></i></p>
</figure>

## 5.2.2 Proving the Ω(n log n) lower bound

!!! note "Proof: The worst-case time complexity of any comparison-based sorting algorithm is Ω (𝑛 log 𝑛) ."

    !!! note inline end "Sterling Approximation"

        Stirling's approximation formula for the factorial of a large integer \(n\) is \(n!\approx \sqrt{2\pi n}(\frac{n}{e})^{n}\). This approximation is used to estimate large factorials that would be difficult or impossible to calculate directly, providing a close approximation to the actual value.
    1. The decision tree must have at least n! leaves to account for all possible input permutations.

    2. A binary tree of height h has at most 2ʰ leaves. Therefore, 2ʰ ≥ n!. (Remember: height of the decision tree (number of comparisons in the worst case) )
    3.  Taking logarithms: h ≥ log₂(n!).

           ***The factorial function $𝑛!$ grows extremely fast. It’s hard to directly compute or simplify $log_2 (𝑛!)$ in terms of 𝑛***

    4. Using Stirling's Approximation $$ n! ≈ \sqrt {2πn}(\frac{n}{e})ⁿ $$,

           we get:
    $$
        \begin{align*}
        \log_2(n!) &\approx \log_2(\sqrt{2\pi n}) + n\log_2\!\left(\frac{n}{e}\right) \\
         &\approx n\log_2 n - n\log_2 e + \tfrac{1}{2}\log_2(2\pi n) \\
         &\approx n\log_2 n - n\log_2 e + O(\log n)
         \end{align*}
    $$

    The other terms are much smaller in magnitude compared to $𝑛 log_2 𝑛 $

    This simplifies to $h = Ω(n log n)$.

    Conclusion: The height of the decision tree (which represents the number of comparisons in the worst case) is Ω(n log n).

## 5.2.3 Implications of the lower bound

Merge Sort and Heap Sort are asymptotically optimal comparison-based sorts because their worst-case running time O(n log n) matches the lower bound Ω(n log n). It is impossible to create a general-purpose comparison sort that is faster than this in the worst case.

## 5.2.4 Limitations of the lower bound proof

This proof only applies to comparison-based sorts. It does not apply to algorithms that leverage other information about the data, such as:

- The integer structure of keys (e.g., Counting Sort, Radix Sort).
- The distribution of the keys.
  These "non-comparison" sorts can achieve O(n) time, breaking the n log n barrier.
