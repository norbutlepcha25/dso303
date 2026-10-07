# 6.4 Longest Common Subequence

> The Longest Common Subsequence (LCS) problem is a classic dynamic programming problem that finds the longest sequence of characters that appear in the same order (but not necessarily contiguously) in two given strings.

## 6.4.1 Problem definition and applications

Given two sequences X[1..m] and Y[1..n], find the length of the longest sequence Z that is a subsequence of both X and Y.

Sequence 1: "ABCDGH"
Sequence 2: "AEDFHR"
LCS: "ADH" (length 3)

Sequence 1: "AGGTAB"
Sequence 2: "GXTXAYB"
LCS: "GTAB" (length 4)

!!! danger "Note"

    A subsequence is derived by deleting zero or more elements without changing the order. The LCS does not require consecutive characters. Also note the following:

    - Substring: Must be contiguous (e.g., "BCD" from "ABCDE")

    - Subsequence: Can be non-contiguous but must maintain order (e.g., "ACE" from "ABCDE")

**Application of this Algorithm**

| Domain                                | Use of LCS                                                                      |
| ------------------------------------- | ------------------------------------------------------------------------------- |
| **Bioinformatics**                    | Comparing DNA or protein sequences for similarity (e.g., gene alignment).       |
| **File/Version Control**              | Tools like Git, diff, and patch use LCS to find line differences between files. |
| **Text Processing**                   | Spell checking and plagiarism detection by comparing sentences or documents.    |
| **Data Compression**                  | Identify repeated patterns in data.                                             |
| **Natural Language Processing (NLP)** | Used in sequence alignment, machine translation evaluation (e.g., BLEU score).  |

## 6.4.2 Recursive formulation

We can break down the LCS problem into smaller subproblems based on the last characters of the sequences. Let LCS(X[1..i], Y[1..j]) be the length of LCS of first i characters of X and first j characters of Y.

**Formula**

$$
LCS(i,j) =
\begin{cases}
0 &\text{if } i=0 \text{ or } j=0 \\
LCS(i-1, j-1)+1 &\text{if } x_i = y_j \\
max (LCS(i-1, j), LCS(i, j-1)) &\text{if } x_i \not = y_j \\
\end{cases}
$$

??? note "Explanation"

    - If either string is empty → LCS length = 0.

    - If last characters match → count it and move diagonally (reduce both i and j).

    - If last characters don’t match → move in the direction that gives a longer LCS (either skip one from X or from Y).

Problem with Naive Recursion

- Time Complexity: $O(2^{m+n})$ in worst case
- Cause: Overlapping subproblems computed repeatedly

## 6.4.3 Dynamic programming algorithm

We build a 2D table dp[m+1][n+1] where dp[i][j] stores the length of LCS of X[0..i-1] and Y[0..j-1].

To solve

1. Create a 2D DP table dp[m+1][n+1]
2. Initialize first row and first column to 0 (base case).
3. Fill the table using recurrence:

```
   if X[i-1] == Y[j-1]:
       dp[i][j] = dp[i-1][j-1] + 1
   else:
       dp[i][j] = max(dp[i-1][j], dp[i][j-1])
```

!!! tip "Remeber"

    | 0 | T |
    | --- | --- |
    | L | X |

    To calculate the value of X you have to check this conditions:

    1. if the row and column header value is same, add 1 to the diagonal element and place ↖
    2. if it is not same, take the max of either 0, Top or Left add ↑, ←  repectively

!!! example "example"

    X = "ABCBDAB"
    Y = "BDCABA"

    |   |   | B | D | C | A | B | A |
    | - | - | - | - | - | - | - | - |
    |   | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
    | A | 0  ↑ | 0  ↑ | 0 ↑ | 0 ↑ | ↖ 1 | ← 1 | ↖ 1 |
    | B | 0 | ↖1 |  ← 1 | ← 1 | ← 1 | ↖2 | ← 2 |
    | C | 0 | ↑ 1 | ↑ 1 | ↖ 2 | ← 2 | ← 2 | ← 2 |
    | B | 0 | ***↖ 1*** | ← 1 | ← 2 | ← 2 | ↖ 3 | ← 3 |
    | D | 0 | ↑ 1 | ***↖2***| ← 2 | ← 2 | ↑ 3 | ← 3 |
    | A | 0 | ↑ 1 | ← 2 | ← 2 | ***↖ 3*** | ← 3 | ↖ 4 |
    | B | 0 | ↑ 1 | ↑ 2 | ↑ 2 | ↑ 3 | ***↖4*** | ← 4 |\

    Longest common Subsequnce : BADB

Time Complexity: $O(m × n)$

Space Complexity: $O(m × n)$

!!! info "Fun Fact"

    This DP approach was formalized by David Sankoff in 1972 for biological sequence alignment —
    it’s the foundation of modern bioinformatics tools like BLAST and Clustal.

<!-- ## 6.4.4 Space-optimized solution -->
