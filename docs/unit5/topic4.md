# 5.4 Randomised Quicksort and Analysis

## 5.4.1 Introduction to randomization in algorithms

Randomization is the process of making random choices during algorithm execution to reduce the chance of encountering worst-case inputs.

In deterministic algorithms (like normal Quicksort with the first element as pivot), a specific input can always cause the worst-case time.
→ Example: If the input array is already sorted, Quicksort’s time becomes $𝑂(𝑛^2)$.

To avoid this, we randomize certain decisions (like pivot selection) so that the algorithm’s behavior depends on random choices, not on the specific input order.

Why Use Randomization?
The primary motivation is to protect against the worst-case scenario. For many deterministic algorithms, an adversary can craft an input that forces the algorithm into its worst-case performance. By introducing randomness, we make the algorithm's behavior unpredictable, making it impossible for an adversary to design such a bad input.

## 5.4.2 Randomized pivot selection in Quicksort

The Problem with Deterministic Picks:
The standard deterministic Quicksort can have a worst-case time complexity of O(n²). This happens when the chosen pivot (e.g., the first or last element) is consistently the smallest or largest element in the current sub-array, leading to highly unbalanced partitions.

Example: Sorting an already sorted array [1, 2, 3, 4, 5] with the last element as the pivot.

The Solution: Random Pivot
Instead of picking a fixed element as the pivot, we choose a pivot uniformly at random from the current sub-array. This simple change is what makes it Randomized Quicksort.

How it works:

When called to sort a sub-array arr[low..high], randomly select an index pivot_index between low and high.

Swap the element at pivot_index with the element at arr[high] (or arr[low]). This places our random pivot in a conventional position for the partitioning step.

Proceed with the standard partition process.

```
RANDOMIZED_QUICKSORT(A, low, high):
    if low < high:
        pivot_index = RANDOMIZED_PARTITION(A, low, high)
        RANDOMIZED_QUICKSORT(A, low, pivot_index - 1)
        RANDOMIZED_QUICKSORT(A, pivot_index + 1, high)


RANDOMIZED_PARTITION(A, low, high):
    i = random(low, high)
    swap A[i], A[high]          # Place random pivot at the end
    return PARTITION(A, low, high)

```

## 5.4.3 Probabilistic analysis of Randomized Quicksort

Key Insight: The time complexity of Randomized Quicksort depends on:

- How the pivot divides the array at each step, i.e based on the comparison it does.
- The probability distribution of these division

!!! danger inline end "Remember"

    Two elements are compared **if and only if** one of them is chosen as pivot before any element between them is chosen as pivot.

let:

$X$ = Total number of comparisons made by Randomized Quicksort

and $X_{ij}$ as Indicator random variable

$$
X_{ᵢⱼ} = \begin{cases}
1 &\text {if elements i and j are compared} \\
0 &\text{otherwise}
\end{cases}
$$

Then the set will contain $j-i+1$ elements

let:

$Z_i$, $Z_{i+1}$ ... $Z_{n}$ be the elements in a sorted order in array A,

for element $Z_i$ and $Z_j$ consider a set

$$
S_{ij} = \{Z_{i}, Z_{i+1} ... Z_{j}\}
$$

??? example "Example"

    lets say $Z_1 < Z_2 < Z_3 < Z_4 < Z_5$ are sorted elements

    say $Z_2$ and $Z_4$ are to be compared

    There are 3 possible pivots in that subset : $Z_2, Z_3, Z_4$

    $Z_2$ and $Z_4$ will only be compared if and only if either of the term is selected as a pivot and the probability of doing so is:
    $$ P_r |X_{ij}| = 1 = \frac{2}{3} $$

!!! note "Remember"

    1. $Z_i$ and $Z_j$ will only be compared if and only if either of the term is selected as a pivot first
    2. Each Element in the $S_{ij}$ is equally likely to be choosen
    3. With N Elements in total, and 2 probable outcome

$$
    \begin{align*}
    P_r\{Z_i \text{ is compared to } Z_j\} \\ \\
    & \implies P_r[Z_i] + P_r[Z_j] \\ \\
    & \implies \frac{1}{j-i+1} + \frac{1}{j-i+1} \\ \\
    & \implies \frac{2}{j-i+1}
    \end{align*}
$$

Total comparison is represented by

$$\boxed{X = \sum_{i=1}^{n-1} \sum_{j=i+1}^n X_{ij}}$$

therefore, expected total comparison is

$$\Epsilon |X| = \Epsilon [\sum_{i=1}^{n-1} \sum_{j=i+1}^n X_{ij}]$$

Using Linearity of Expection

$$\Epsilon |X| =  \sum_{i=1}^{n-1} \sum_{j=i+1}^n \Epsilon X_{ij}$$

Since

$$\Epsilon X_{ij} = \Pr  (X_{ij}=1) = \frac{2}{j-i+1}$$

$$\Epsilon |X| =  \sum_{i=1}^{n-1} \sum_{j=i+1}^n \frac{2}{j-i+1}$$

Let $k=j-i$ then $j-i+1$ = $K+1$

$$\Epsilon |X| =  \sum_{i=1}^{n-1} \sum_{K=1}^{n-i} \frac{2}{K+1}$$

!!! note inline end "Hermonic Series"

    Hermonic Series $H_n$ :

    $$
    H_n = \sum_{k=1}^n \frac{1}{k} = 1 + \frac{1}{2} + \frac{1}{3} + ... + \frac{1}{n}$$

Looking at the inner sum , which seems to reprent a similar pattern to hermonic Series we get:

$$\sum_{k=1}^{n-i} \frac{2}{K+1} =  2 ( \frac{1}{2} + \frac{1}{3} + ... + \frac{1}{n-i+1})$$

$$H_{n-i+1}=  1+ \frac{1}{2} + \frac{1}{3} + ... + \frac{1}{n-i+1}$$

substituing it

$$\Epsilon |X| =  2 \sum_{i=1}^{n-1} H_{n-i+1}$$

The upper bound for this should not exceed $H_n - 1$, therefore

$$\Epsilon |X| =  2 \sum_{i=1}^{n-1} H_{n-i+1} -1 \le 2 \sum_{i=1}^{n-1} H_n -1$$

$$\sum_{i=1}^{n-1} H_n -1་ \implies 2(n-1)(H_n-1)$$

As $H-n = \ln n + \gamma$, where $\gamma$ = 0.577 (Euler Mascharoni identity)

$$\Epsilon |X| \le 2(n-1)(H_n-1)$$

$$\Epsilon |X| \le 2(n-1)(ln n + \gamma -1)$$

$$2(n-1)\ln n + 2(n-1)(\gamma) - 2(n-1)$$

Taking the dominanat Influence $2(n-1)\ln n$ $\approx nlogn$

## 5.4.4 Advantages of randomization in sorting
