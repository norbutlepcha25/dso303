# Efficient Modular Exponentiation

Modular exponentiation is a technique to compute: $(a^b) \mod m$ efficiently

It’s widely used in **cryptography**, **number theory**, and **computer algorithms**, especially when the exponent \( b \) is very large.

---

### 4.6.1 Naive Approach to Modular Exponentiation

**Idea:**

The naive method directly computes \( a^b \) and then takes modulo \( m \).

\[
result = (a^b) \mod m
\]

**Algorithm:**

1. Initialize `result = 1`
2. Multiply `result` by `a`, `b` times
3. Take modulo \( m \) at the end.

**Pseudocode:**

```python
def naive_modular_pow(a, b, m):
    result = 1
    for i in range(b):
        result = result * a
    return result % m
```

Time Complexity: **O(b)** multiplications
Impractical for large exponents: If b = $2^{1000}$, we'd need $2^{1000}$ multiplications
Example: Computing $5^{100} \mod 13$ would require 100 multiplications
Even with modular reduction at each step, still too slow for cryptographic purposes

### 4.6.2 Square-and-multiply algorithm

Write the exponent \(b\) in binary and use its bits to decide when to multiply. This reduces the number of multiplications to about the number of bits in \(b\) (i.e., \(O(\log b)\)).

**Step**

To compute $a^b \mod m$

1.  Convert the Exponent "b" to Binary
2.  Start from the most significant bit (MSB).
3.  initialize result = 1
4.  For each bit in the binary representation (from left to right):

    - Square the current result
    - If the current bit is 1, multiply by the base a
    - Take modulo 𝑚 after each step.

!!! example "Example"

    Question : $10^{25} \mod 58$

    - **step 1**: convert 25 to binary : $25_{10} = (11001)_2$
    - **step 2**: result = 1
    - **step 3**:
        - checking first bit is equal  to 1, therefore sqaure the result and multiply with base "a" and find the modulo
        - $1^2 \times 10 \mod 58$ = 10
        - update the table

    |Bits → | 1 | 1 | 0 | 0 | 1 |
    |-------|---|---|---|---|---|
    |result →| 10|   |   |   |   |

    - **step 4**:
        - checking second bit is equal  to 1, therefore sqaure the result and multiply with base "a" and find the modulo
        - $10^2 \times 10 \mod 58$ = 14
        - update the table

    |Bits → | 1 | 1 | 0 | 0 | 1 |
    |-------|---|---|---|---|---|
    |result → | 10| 14  |   |   |   |

    - **step 5**:
        - checking second bit is equal  to 0, therefore sqaure the result and find the modulo
        - $14^2 \mod 58$ = 22
        - update the table

    |Bits → | 1 | 1 | 0 | 0 | 1 |
    |-------|---|---|---|---|---|
    |result → | 10| 14  | 22  |   |   |

    - **step 6**:
        - checking second bit is equal  to 0, therefore sqaure the result and multiply with base "a" and find the modulo
        - $22^2 \mod 58$ = 20
        - update the table

    |Bits → | 1 | 1 | 0 | 0 | 1 |
    |----|---|---|---|---|---|
    |result → | 10| 14  | 22  | 20 |   |

    - step 7:
        - checking second bit is equal  to 1, therefore sqaure the result and multiply with base "a" and find the modulo
        - $00^2 \times 10 \mod 58$ = 56
        - update the table

    |Bits → | 1 | 1 | 0 | 0 | 1 |
    |----|---|---|---|---|---|
    |result → | 10| 14  |  22 | 20  | 56  |

    ** final result** : $10^{25} \mod 58$ = 56

```
function modular_exponentiation(base, exponent, modulus):
    result = 1
    base = base mod modulus

    while exponent > 0:
        if exponent is odd:
            result = (result × base) mod modulus
        base = (base × base) mod modulus
        exponent = exponent >> 1  // right shift (divide by 2)

    return result
```

**Time Complexity**

- Bit length of exponent: $k = ⌈log₂(b)⌉$
- Number of squarings: $k - 1$ (one for each bit except the first)
- Number of multiplications: Approximately $k/2$ on average (for half the bits being 1) i.e, Each iteration halves the exponent.
- Total operations: O(k) = $O(log b)$ modular multiplications
- Modulo at every step keeps numbers manageable.
- Comparison: Naive O(b) vs Efficient O(log b)

### 4.6.3 Applications in Cryptography

1.  RSA Cryptosystem

    - Encryption: $c = m^e \mod n$
    - Decryption: $m = c^d \mod n$

    Where e (public exponent) and d (private exponent) are large numbers
    Efficient modular exponentiation is essential for practical RSA

2.  Diffie-Hellman Key Exchange

    - Key computation: $K = g^{(ab)} \mod p$
    - Both parties compute shared secret using large exponents
    - Security relies on difficulty of discrete logarithm problem

3.  Digital Signatures (DSA, ECDSA)

    - Signature verification involves modular exponentiation
    - Must verify signatures efficiently in real-time applications

## 4.7 Efficient Matrix Modular Exponentiation
