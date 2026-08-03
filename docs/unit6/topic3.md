# 6.3 Matrix Chain Multiplication

Given a chain ${A_1, A_2, A_3, .. A_n}$ of $n$ matrices, where for $i = 1,2,3 ... n$, matrix $A_i$ has dimension $p_{i-1}, p_i$, fully parenthesize the product ${A_1, A_2, A_3, .. A_n}$ in a way that minimizes the number of scalar multiplications i.e, given a sequence of Matrix we want to find the best sequence to multiply them together.

!!! warning "Remember"

     Matrix multiplication as associative in nature but not commutative.

     Example: $A \cdot (B \cdot C)$ = $(A \cdot B ) \cdot C$ but $A \cdot B \not = B \cdot A$

Although the matrix multiplication is associative in nature, however the number of computation (scalar Multiplication) depends on he sequence of operation that is done.

!!! example "exmple"

    !!! info inline end "Tips"
        1. Multiplying two matrix $A_{a \times b}$ and $B_{b \times c}$, the product will have a dimention of $R_{a \times c}$
        1. Multiplying two matrix $A_{a \times b}$ and $B_{b \times c}$, number of multiplication = $a \times b \times c$
    Lets say there are three Matrix $A_{10 \times 5},\quad B_{5\times 20},\quad C_{20\times 10}$, so we have two ways to multiply it, therefore the required number of computation is :

    1. $(A \cdot B ) \cdot C$

        =$(10 \times 5 \times 20)$ + $(10 \times 20 \times 10)$

        = 1000 + 2000

        = 3000
    2. $A \cdot (B  \cdot C)$

        =$(10 \times 5 \times 10)$ + $(5 \times 20 \times 10)$

        = 500 + 1000

        = 1500

    Although both the matrix multiplications will yield the same result, the number of multiplication required will depend on the sequence or optimal parenthesization of the sequence of array.

The Recursive definition for the minimum cost of parenthesizing the product $A_i,\quad A_{i+1} \quad ... A_j$ becomes

$$
m[i, j] =
\begin{cases}
    0, & \text{if } i = j \\
    \displaystyle \min_{i \le k < j} \{\, m[i,k] + m[k+1,j] + P_{i-1} \cdot P_k \cdot P_j \,\}, & \text{if } i < j
\end{cases}
$$

!!! example "Example"

    $$
    \begin{array}{c|cccc}
    \text{Matrix} & A_1 & A_2 & A_3 & A_4 \\ \hline
    \text{Dimension} & 5 \times 4 & 4 \times 6 & 6 \times 2 & 2 \times 7
    \end{array}
    $$

    Here,
    $P = [5, 4, 6, 2, 7]$
    represents the matrix dimensions for the chain $A_1 A_2 A_3 A_4$, where matrix $A_i$ has dimension $P_{i-1} \times P_i$.


    1) Minimum Multiplication Cost Table $m[i,j]$

       - $m[1,2] = 5 \cdot 4 \cdot 6 = 120$
       - $m[2,3] = 4 \cdot 6 \cdot 2 = 48$
       - $m[3,4] = 6 \cdot 2 \cdot 7 = 84$

    | i \ j |  1  |  2  |  3  |  4  |
    | :---: | :-: | :-: | :-: | :-: |
    | **1** |  0  | 120 | -   | - |
    | **2** |     |  0  | 48  | - |
    | **3** |     |     |  0  | 84  |
    | **4** |     |     |     |  0  |

    Split Table $s[i,j]$ (Optimal split positions)

    | i \ j |  1  |  2  |  3  |  4  |
    | :---: | :-: | :-: | :-: | :-: |
    | **1** |  -  |  1  |  -  |  -  |
    | **2** |     |  -  |  2  |  -  |
    | **3** |     |     |  -  |  3  |
    | **4** |     |     |     |  -  |

    2) Minimum Multiplication Cost Table $m[i,j]$

       $m[1,3]$:

       - $k=1: 0 + 48 + 5\cdot4\cdot2 = 88$ ← optimal Solution
       - $k=2: 120 + 0 + 5\cdot6\cdot2 = 180$

       $m[2,4]$:

       - $k=2: 0 + 84 + 4\cdot6\cdot7 = 252$
       - $k=3: 48 + 0 + 4\cdot2\cdot7 = 104$ ← optimal Solution

    | i \ j |  1  |  2  |  3  |  4  |
    | :---: | :-: | :-: | :-: | :-: |
    | **1** |  0  | 120 | 88   | - |
    | **2** |     |  0  | 48  | 104 |
    | **3** |     |     |  0  | 84  |
    | **4** |     |     |     |  0  |

    Split Table $s[i,j]$ (Optimal split positions)

    | i \ j |  1  |  2  |  3  |  4  |
    | :---: | :-: | :-: | :-: | :-: |
    | **1** |  -  |  1  |  1  |  -  |
    | **2** |     |  -  |  2  |  3  |
    | **3** |     |     |  -  |  3  |
    | **4** |     |     |     |  -  |

    3) Minimum Multiplication Cost Table $m[i,j]$

    Full chain $m[1,4]$:

     - $k=1: 0 + 104 + 5\cdot4\cdot7 = 244$
     - $k=2: 120 + 84 + 5\cdot6\cdot7 = 414$
     - $k=3: 88 + 0 + 5\cdot2\cdot7 = 158$ ← optimal Solution

    !!! Note inline end ""

        $m[1,4]=158$ is the minimum number of scalar multiplications to compute $A_1A_2A_3A_4$.

    | i \ j |  1  |  2  |  3  |  4  |
    | :---: | :-: | :-: | :-: | :-: |
    | **1** |  0  | 120 | 88  | 158 |
    | **2** |     |  0  | 48  | 104 |
    | **3** |     |     |  0  | 84  |
    | **4** |     |     |     |  0  |

    !!! Note inline end "Interpretation"

        e.g., $s[1,3]=1$ means the optimal split for $m[1,3]$ is at $k=1$ (i.e., $(A_1)(A_2A_3)$).

    | i \ j |  1  |  2  |  3  |  4  |
    | :---: | :-: | :-: | :-: | :-: |
    | **1** |  -  |  1  |  1  |  3  |
    | **2** |     |  -  |  2  |  3  |
    | **3** |     |     |  -  |  3  |
    | **4** |     |     |     |  -  |

    Therefore, optimal Parenthesization : $( (A_1 \times (A_2 \times A_3)) \times A_4 )$
