# Unit 0

## Algorithms: An Overview

## 1. What are Algorithms?

- An **algorithm** is a finite sequence of well-defined instructions for solving a specific problem or performing a computation.
- Algorithms take an input, process it through defined steps, and produce an output.
- Characteristics of algorithms:
  - **Definiteness**: Each step is clear and unambiguous.
  - **Finiteness**: Must terminate after a finite number of steps.
  - **Input**: Accepts zero or more inputs.
  - **Output**: Produces at least one output.
  - **Effectiveness**: Steps are simple enough to be executed within finite time.

**Examples**:

- Sorting numbers (e.g., Merge Sort, Quick Sort).
- Searching for an element (e.g., Binary Search).
- Graph algorithms (e.g., Dijkstra’s shortest path).

---

## 2. Why is the Study of Algorithms Worthwhile?

- **Efficiency Matters**: Determines how quickly and efficiently problems are solved.
- **Scalability**: Good algorithms handle large inputs effectively.
- **Optimization**: Improves resource usage (time, memory, bandwidth, etc.).
- **Foundational Knowledge**: Core of computer science and problem solving.
- **Innovation**: New algorithms lead to advancements in AI, cryptography, networking, etc.
- **Competitive Advantage**: Faster, more efficient systems outperform less optimized ones.

---

## 3. The Role of Algorithms Relative to Other Technologies

- **Hardware**: Provides raw computational power.
- **Software**: Implements instructions to perform tasks.
- **Algorithms**: Bridge between hardware and software efficiency.
  - Example: A slow algorithm on a fast computer still produces slow results.
- Algorithms optimize the use of hardware and software by minimizing time and space requirements.

**Illustration**:

- A good sorting algorithm (like Merge Sort) can handle millions of records efficiently, whereas a naive sorting approach may take impractical amounts of time even on modern processors.

---

## 4. Role of Algorithms for Software Engineers

- **Problem-Solving Skills**: Helps design solutions to complex problems.
- **Efficiency in Development**: Better algorithms reduce code complexity and execution time.
- **System Design**: Crucial for scalable and reliable systems.
- **Competitive Programming & Interviews**: Strong algorithm knowledge is essential for coding assessments.
- **Practical Applications**:
  - Database query optimization.
  - Network routing.
  - Machine learning training.
  - Real-time systems.

---

## 5. Summary

- Algorithms are the backbone of computing, defining _how_ problems are solved.
- Studying algorithms equips software engineers with tools to build **efficient, scalable, and optimized systems**.
- They complement hardware and software technologies by making computation feasible and practical.

## Useful Mathematical Formulas

When we analyze algorithms, we often need to use various mathematical tools. Thus, it is useful to take note of some of the basic mathematical formulas.

### 1. Summations

1. For a given sequence _a~1~_,_a~2~_,_a~3~_, ... _a~n~_, where _n_ is a non negative integer we can write the finite sum _a~1~_+_a~2~_+_a~3~_+ ... +_a~n~_ as

$$
\sum_{k=1} ^{n} n_k
$$

#### 1. Arithmetic Series

$$
\sum_{i=1}^{n} i = \frac{n(n+1)}{2} = \Theta(n^2)
$$

$$
\sum_{i=1}^{n} (a + (i-1)d) = \frac{n}{2} \big(2a + (n-1)d\big)
$$

---

## 2. Square and Higher Powers

$$
\sum_{i=1}^{n} i^2 = \frac{n(n+1)(2n+1)}{6} = \Theta(n^3)
$$

$$
\sum_{i=1}^{n} i^3 = \left(\frac{n(n+1)}{2}\right)^2 = \Theta(n^4)
$$

---

## 3. Geometric Series

$$
\sum_{i=0}^{n} r^i = \frac{r^{n+1} - 1}{r - 1}, \quad r \neq 1
$$

$$
\sum_{i=0}^{\infty} r^i = \frac{1}{1-r}, \quad |r| < 1
$$

---

## 4. Harmonic Series

$$
H_n = \sum_{i=1}^{n} \frac{1}{i} \approx \ln n + \gamma
$$

where $\gamma \approx 0.577$ is the Euler–Mascheroni constant.

$$
\sum_{i=1}^{n} \frac{1}{i} = \Theta(\log n)
$$

---

## 5. Logarithmic Summations

$$
\sum_{i=1}^{n} \log i = \log(n!) \approx n \log n - n
$$

$$
\sum_{i=1}^{n} \log n = n \log n
$$

$$
\sum_{i=0}^{\log n} 2^i = 2^{\log n + 1} - 1 = 2n - 1
$$

---

## 6. Useful Asymptotics

- $\sum_{i=1}^{n} c = cn = \Theta(n)$
- $\sum_{i=1}^{n} i^k = \Theta(n^{k+1})$
- $\sum_{i=1}^{\log n} n = n \log n$

---