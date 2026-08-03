# Efficient Matrix Modular Exponentiation

> Matrix modular exponentiation is an extension of modular exponentiation from scalar numbers to matrices. It is a powerful technique used in various computational problems, especially where recurrence relations or transitions between states can be modeled using matrices.

In standard modular exponentiation, we compute $a^b \mod m$ whereas in **matrix modular exponentiation**, we instead compute:

$$
\boxed{A^n \mod m}
$$

where **A** is a square matrix, **n** is a non-negative integer (the exponent), and **m** is the modulus.

**Steps in Left-to-Right Matrix Modular Exponentiation**

- Step 1: Convert the Exponent to Binary

       - Write `n` in binary form.

- Step 2: Initialize result

       - `result = I` (identity matrix)
       - `base = A`

- Step 3: Process Each Bit (Left → Right)

For each bit **b** in the binary representation of `n` (starting from the **leftmost bit**):

1. **Square the current result**  
   $
   result = (result × result) \mod m
   $

2. **If the current bit is 1**, multiply by the base matrix:
   $
   result = (result × A) \mod m
   $

---

$$
A^{10} \mod 1000
$$

where

$$
A =
\begin{bmatrix}
1 & 1 \\
1 & 0
\end{bmatrix}
$$

---

#### Step 1: Convert the Exponent to Binary

$$
10_{10} = 1010_2
$$

- Bit 1 (MSB = 1)
- result = result² = I
- multiply by A:
- result = $I^2 \times A = A$

$$
\begin{bmatrix}
1 & 0 \\
0 & 1
\end{bmatrix}
\times
\begin{bmatrix}
1 & 1 \\
1 & 0
\end{bmatrix}
=
\begin{bmatrix}
1 & 1 \\
1 & 0
\end{bmatrix}
$$

- Bit 2 (next = 0)
- Square the result : $A^2$
- Bit = 0 → don’t multiply

$$
\begin{bmatrix}
1 & 1 \\
1 & 0
\end{bmatrix}
\times
\begin{bmatrix}
1 & 1 \\
1 & 0
\end{bmatrix}
=
\begin{bmatrix}
2 & 1 \\
1 & 1
\end{bmatrix}
$$

- Bit 3 (next = 1)
- Square the result : $(A^2)^2 = A^4$

$$
\begin{bmatrix}
2 & 1 \\
1 & 1
\end{bmatrix}
\times
\begin{bmatrix}
2 & 1 \\
1 & 1
\end{bmatrix}
=
\begin{bmatrix}
5 & 3 \\
3 & 2
\end{bmatrix}
$$

- Bit = 1 → multiply by A i.e, $A^4 \times A$

$$
\begin{bmatrix}
5 & 3 \\
3 & 2
\end{bmatrix}
\times
\begin{bmatrix}
1 & 1 \\
1 & 0
\end{bmatrix}
=
\begin{bmatrix}
8 & 5 \\
5 & 3
\end{bmatrix}
$$

- Bit 4 (last = 0)
- Square result = $(A⁵)² = A¹⁰$:
  $$
  $$

$$
\begin{bmatrix}
8 & 5 \\
5 & 3
\end{bmatrix}
\times
\begin{bmatrix}
8 & 5 \\
5 & 3
\end{bmatrix}
=
\begin{bmatrix}
88 & 55 \\
55 & 34
\end{bmatrix}
$$

- Bit = 0 → no multiply.

The time complexity of efficient matrix modular exponentiation is O(D³ log E), where:

D: represents the dimension of the square matrix (e.g., for a 2x2 matrix, D=2).

E: represents the exponent to which the matrix is raised.
