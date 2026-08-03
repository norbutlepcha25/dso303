# Matrix Multiplication

### 4.2.1 Standard Matrix Multiplication

Given a square matrix, the standard way of multiplying any sqaure matrix is as follow.

Given two 𝑛 × 𝑛 matrices(square matrix) 𝐴 and 𝐵, the product $𝐶 = 𝐴×𝐵$ is also an $𝑛×𝑛$ matrix where

$$
\boxed{
 𝐶_{𝑖𝑗}=∑_{𝑘=1}^𝑛𝐴_{𝑖𝑘}⋅𝐵_{𝑘𝑗}}
$$

Lets understand the above formula with a pseudocode for Square Matrix Multiplication

(**Note**: _Try to analyse the code first and then check the explanation for reference._)

!!! note "Pseudocode for standard Matrix Multiplication"

    ```text
    1 SQUARE MATRIX MULTIPLY(A, B)
    2    n = A.rows
    3    let C be a new n x n matrix
    4    for i = 1 to n
    5        for j = 1 to n
    6            C[i][j] = 0
    7            for k = 1 to n
    8                C[i][j] = C[i][j] + A[i][k] * B[k][j]
    ```

    ??? note "Explanation:"

         1. Intializing a function called **SQUARE MATRIX MULTIPLY** that takes two input parameter A and B, which are both square matix
         2. initialize n= A.rows, will store the size of the row, alternately col can also be used as it is a square matrix
         3. Initializing a new matrix $C$ of size $n \times n$

From a standard matrix multiplication, for every element in the resultant matrix C has to perform **$n$** multiplication and **$(n-1)$** addition i.e, for example 2x2 matrix A multiplied with 2x2 matrix B, so to get the first element $C[i][j]$ it will take 2 multiplication and 1 addition.

The time complexicity of Standard Matrix multiplication is $\Theta (n^3)$

### 4.2.2 Divide and conqure method for Matrix Multiplication

when we use a divide-and-conquer algorithm to compute the matrix product C = A.B, we **_assume that n is an exact power of 2_** in each of the nxn matrices. We make this assumption because in each divide step, we will divide nxn matrices into four n/2 x n/2 matrices, and by assuming that n is an exact power of 2, we are guaranteed that as long as $n \ge 2$, the dimension n=2 is an integer.

Steps:

1. Decompose two 𝑛 × 𝑛 matrices into 4 submatrices of size 𝑛/2 × 𝑛/ 2.
2. Multiply the submatrices recursively.
3. Combine results to form the final product.

Pseudocode for matrix multiplication using divide and conquer

```

SQUARE-MATRIX-MULTIPLY-RECURSIVE (A, B)
1 n = A.rows
2 let C be a new nxn matrix
3 if n == 1
4 C[1][1] = A[1][1].B[1][1]
5 else partition A, B, and C
6 C[1][1] = SQUARE-MATRIX-MULTIPLY-RECURSIVE(A[1][1].B[1][1]) +
    SQUARE-MATRIX-MULTIPLY-RECURSIVE(A[1][2].B[2][1])
7 C[1][2] = SQUARE-MATRIX-MULTIPLY-RECURSIVE(A[1][1].B[1][2]) +
    SQUARE-MATRIX-MULTIPLY-RECURSIVE(A[1][2].B[2][2])
8 C[2][1] = SQUARE-MATRIX-MULTIPLY-RECURSIVE(A[2][1].B[1][1]) +
    SQUARE-MATRIX-MULTIPLY-RECURSIVE(A[2][2].B[2][1])
9 C[2][2] = SQUARE-MATRIX-MULTIPLY-RECURSIVE(A[2][1].B[1][2]) +
    SQUARE-MATRIX-MULTIPLY-RECURSIVE(A[2][2].B[2][2])
10 return C

```

Steps

Let:

$$
A =
\begin{bmatrix}
A_{11} & A_{12} \\
A_{21} & A_{22}
\end{bmatrix},
\quad
B =
\begin{bmatrix}
B_{11} & B_{12} \\
B_{21} & B_{22}
\end{bmatrix} \tag{4.1}
$$

Then the product is:

$$
C = A \times B =
\begin{bmatrix}
C_{11} & C_{12} \\
C_{21} & C_{22}
\end{bmatrix} \tag{4.2}
$$

where:

$$
\begin{aligned}
C_{11} &= A_{11}B_{11} + A_{12}B_{21} \\
C_{12} &= A_{11}B_{12} + A_{12}B_{22} \\
C_{21} &= A_{21}B_{11} + A_{22}B_{21}  \\
C_{22} &= A_{21}B_{12} + A_{22}B_{22}
\end{aligned} \tag{4.3}
$$

---

Recurrence Relation

- Each step requires **8 multiplications** of size \((n/2) \times (n/2)\), plus some additions.

\[
T(n) = 8T\left(\frac{n}{2}\right) + O(n^2)
\]

- Time Complexity

  $$
  T(n) = O(n^3)
  $$

(same as classical matrix multiplication).

---

### 4.2.3 Strassen’s Algorithm

It has four steps:

1.  Divide the input matrices A and B and output matrix C into $\frac{n}{2}$ x $\frac{n}{2}$ submatrices, as in equation (4.1) above. This step takes $\Theta(1)$ time by index calculation.

    $$
    A =
    \begin{bmatrix}
    A_{11} & A_{12} \\
    A_{21} & A_{22}
    \end{bmatrix},
    \quad
    B =
    \begin{bmatrix}
    B_{11} & B_{12} \\
    B_{21} & B_{22}
    \end{bmatrix}
    $$

    and resultant matrix "C" :

    $$
    C = A \times B =
    \begin{bmatrix}
    C_{11} & C_{12} \\
    C_{21} & C_{22}
    \end{bmatrix}
    $$

2.  The values of the resultant matrix C is as follows

    $$
    C =
    \begin{bmatrix}
    m_1+m_4-m_5+m_7 & m_3+m_5 \\
    m_2+m_4 & m_1+m_3-m_2+m_6
    \end{bmatrix}
    $$

    Where

    $$
    \begin{align*}
    m_{1} &= (A_{11} + A_{22}) \times (B_{11} + B_{22}) \implies A_{11} \cdotp B_{11} + A_{11} \cdotp B_{22} + A_{22} \cdotp B_{11} + A_{22} \cdotp B_{22} \\
    m_{2} &= B_{11} \times  (A_{21} + A_{22}) \implies A_{21} \cdotp B_{11} + A_{22} \cdotp B_{11} \\
    m_{3} &= A_{11} \times (B_{12} - B_{22}) \implies A_{11} \cdotp B_{12} -  A_{11} \cdotp  B_{22} \\
    m_{4} &= A_{22} \times (B_{21} - B_{11}) \implies A_{22} \cdotp B_{21} - A_{22} \cdotp B_{11} \\
    m_{5} &= B_{22} \times (A_{11} + A_{12}) \implies A_{11} \cdotp B_{22} + A_{12} \cdotp B_{22} \\
    m_{6} &= (A_{21} - A_{11})\times (B_{11} + B_{12}) \implies A_{21} \cdotp B_{11} + A_{21} \cdotp  B_{12} - A_{11} \cdotp B_{11} - A_{11} \cdotp B_{12}   \\
    m_{7} &= (A_{12} - A_{22})\times (B_{21} + B_{22}) \implies A_{12} \cdotp B_{21} + A_{12} \cdotp B_{22} - A_{22} \cdotp B_{21} - A_{22} \cdotp B_{22}
    \end{align*}
    $$

    **_On solving this, it would give the same result as in eq 4.3_**

Recurrence Relation

- Each step requires **7 multiplications** of size \((n/2) \times (n/2)\), plus a number additions and subtractions.

$$
T(n) = 7T\left(\frac{n}{2}\right) + O(n^2)
$$

- Time Complexity

  $$
  T(n) = O(n^{2.80})
  $$

---

!!! example "Example 1"

    $$
    A =
    \begin{bmatrix}
    1 & 3 \\
    7 & 5
    \end{bmatrix},
    \quad
    B =
    \begin{bmatrix}
    6 & 8 \\
    4 & 2
    \end{bmatrix}
    $$

    $$
    \begin{align*}
    m_{1} &= (1 + 5) \times (6 + 2) = 48 \\
    m_{2} &= 6 \times  (7 + 5) = 72 \\
    m_{3} &= 1 \times (8 - 2) =  6 \\
    m_{4} &= 5 \times (4 - 6) = -10 \\
    m_{5} &= 2 \times (1 + 3) = 8 \\
    m_{6} &= (7 - 1)\times (6 + 8) = 84   \\
    m_{7} &= (3- 5)\times (4 + 2) = -12
    \end{align*}
    $$

    Now :

    $$
    C =
    \begin{bmatrix}
    m_1+m_4-m_5+m_7 & m_3+m_5 \\
    m_2+m_4 & m_1+m_3-m_2+m_6
    \end{bmatrix}
    $$

    $$
    \implies C =
    \begin{bmatrix}
    48+(-10)-8+(-12) & 6+8 \\
    72+(-10) & 48+6-72+84
    \end{bmatrix}
    $$

    $$
    \implies C =
    \begin{bmatrix}
    18 & 14 \\
    62 & 66
    \end{bmatrix}
    $$
