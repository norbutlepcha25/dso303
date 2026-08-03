# Master Theorem

#### 1. Master Theorem (Classic)

**Definition:**  
The Master Theorem provides a method to determine the asymptotic time complexity of divide-and-conquer recurrences of the form:

$$
T(n) = a \, T\left(\frac{n}{b}\right) + f(n)
$$

Where:

- \(a \ge 1\) → number of subproblems
- \(b > 1\) → factor by which the problem size is divided
- \(f(n)\) → non-recursive work done per call

!!! success " Cases"

    Case 1: **Recursion dominates:**
    $$
    if \quad f(n) = O(n^{\log_b a - \epsilon}) \; for \; some \; constant \; \epsilon > 0  \quad Result: T(n) = \Theta(n^{\log_b a})
    $$

    Case 2: **Balanced:**
    $$
    f(n) = \Theta(n^{\log_b a}) \quad Result:T(n) = \Theta(n^{\log_b a} \log n)
    $$

    case 3: **Outside work dominates:**
    $$
    f(n) = \Omega(n^{\log_b a + \epsilon}) \; for \; some \; constant \; \epsilon > 0  \quad \text{(with regularity condition)} \quad Result:T(n) = \Theta(f(n))
    $$

    regualarity Condition:
    $$ af(\frac{n}{b}) \le cf(n) $$
    for some constant c < 1 and all sufficiently large n, then
    $$ Result : T(n) = \Theta (f(n)) $$

---

**Steps for Master Theorem**

- From the equation note the values of a, b and $ f(n)$
- calculate the thershold function $ n^{\log_b a} $, let be denoted as $ g(n) $
- compare $f(n)$ with $g(n)$ and check which category it falls into
- Note down the final result

!!! example "Example 1"

     **Q1. $ T(n) = 4T(\frac{n}{2}) + n $**

      step 1: from the given equation noting the required value : $ a = 4, b = 2, f(n) = n$

      step 2: Calcuating Threshold function : $ g(n) = n^{\log_b n} \implies g(n) = n^{\log_2 4} \implies g(n) = n^2$

      step 3: compare the $f(n)$ and $ g(n)$

      $$ f(n) \le g(n) $$
      $$ n \le n^2 $$

      step 4: Case 1 condition satisfied $f(n) = O (n^{log_b a- \epsilon}) $ where $\epsilon > 0$ i.e, $\epsilon = 1$

      step 5: Result : $ T(n) = \Theta (n^ {log_b a} )$
      $$
      \boxed{T(n) = \Theta (n^ 2)}
      $$

      **Q2. $ T(n) = T(\frac{n}{2}) + 1$**

      step 1: from the given equation noting the required value : $ a = 1, b = 2, f(n) = 1$

      step 2: Calcuating Threshold function : $ g(n) = n^{\log_b n} \implies g(n) = n^{\log_2 1} \implies g(n) = n^0 = 1$

      step 3: compare the $f(n)$ and $ g(n)$

      $$ f(n) = g(n) $$
      $$ 1 = 1 $$

      step 4: Case 2 condition satisfied $f(n) = \theta (n^{log_b a}) $

      step 5: Result : $ T(n) = \Theta (n^ {log_b a} \log n)$
      $$
      \boxed{T(n) = \Theta (log n)}
      $$
       **Q3. $ T(n) = 2T(\frac{n}{2}) + n^4$**

      step 1: from the given equation noting the required value : $ a = 2, b = 2, f(n) = n^4$

      step 2: Calcuating Threshold function : $ g(n) = n^{\log_b n} \implies g(n) = n^{\log_2 2} \implies g(n) = n^1 = n$

      step 3: compare the $f(n)$ and $ g(n)$

      $$ f(n) > g(n) $$
      $$ n^4 = n $$

      step 4: Case 3 : thus, go for regularity condition check
      condition satisfied i.e, $af(\frac{n}{b}) \le cf(n) $

     $$af(\frac{n}{b}) \le cf(n) $$

      $$
      2 \cdot (n^{4} /2^{4}) \le c \cdot n^{4}
      $$
      $$
       (\frac{1}{8}) \le c \cdot 1
      $$

      $\therefore $ condition holds for the regularity check


      step 5: Result : $ T(n) = \Theta (n^ {4} )$

      $$
      \boxed{T(n) = \Theta (n^4)}
      $$

---

#### 2. Generalized Master Theorem

**Definition:**  
The Generalized Master Theorem generalizes the Master Theorem to handle recurrences where \(f(n)\) has **logarithmic factors**, i.e.,

$$
T(n) = a \, T\left(\frac{n}{b}\right) + f(n)
$$

where

$$
f(n) = \Theta(n^{\log_b a} \cdot \log^k n), \quad k \ge 0
$$

!!! tip ""

     Use this formula if there is no <unit3:polynomial growth> or directly when you use log function in the addtional cost for other function

!!! note "Intution behind the Generalized Master Theorem"

      Lets say for example a recurrence relation is represented by $T(n) = 2T(\frac{n}{2})+nlogn$

      if we used the Classic Master theorem than
      $$ a= 2, b=2, f(n) = n \log n$$

      - calculating the $g(n)$, we get $g(n)= n$

      - comparing $f(n)$ and $g(n)$, we can see that $f(n)$ is greater than $g(n)$ and we might say that CASE 3 applies and proceed to check the regularity condition. However, that would be an **{==Error==}** as the function $f(n)$ is growing logrithmically with respect to $g(n)$ and not polynomially. (see <unit3:polynomial Growth>). Thus classic master theorem cannot be applied to this recurrence relation.

      - for such recurrence relations we use the generalized master theorem which takes into account the logarithmic factors

!!! success "Cases"

    Case 1: **k > -1**
    $$
    T(n) = \Theta(n^{\log_b a} \log^{k+1} n)
    $$

    Case 2: **k = -1**
    $$
    T(n) = \Theta(n^{\log_b a} \log \log n)
    $$

    Case 3: **k < 1**
    $$
    T(n) = \Theta(n^{\log_b a} )
    $$

!!! example "Example"

     **Q1. $ (T(n) = 2T(n/2) + n \log n\) $**

      $$ a=2, b=2, f(n)= n \log n k=1$$

      Classic Master theorem cannot be applied here thus, using the generalized Master theorem for $k=1$

      Result: $T(n) = \Theta(n^{\log_b a} \log^{k+1} n)$

      Thus final Answer:

      $$
      \boxed{T(n) = \Theta(n \log^2 n)}
      $$

#### 3. Extended Master Theorem

**Definition:**

$$
T(n) = a \, T\left(\frac{n}{b}\right) + f(n)
$$

where

$$
f(n) = \Theta(n^k \cdot \log^p n), \quad k \ge 0
$$

**Steps for Master Theorem**

- From the equation note the values of a, b , k and p
- calculate the $ b^k $
- compare $a$ with $b^k$ and check which category it falls into and the value of p
- Note down the final result

!!! success "Case 1: **$ a > b^k $** "

    $$
    T(n) = \Theta(n^{\log_b a})
    $$

!!! success "Case 2: **$ a = b^k $**"

      Then check the value of p

    $$ p > -1 \: then \: result \:  T(n) = \Theta(n^{k} \log^{p+1} n) $$

    $$
    p = -1 \: then \: result \:  T(n) = \Theta(n^{k} \log \log n)
    $$

    $$
    p < -1 \: then \: result \:  T(n) = \Theta(n^{k} )
    $$

!!! success "Case 3: **$ a < b^k $**"

    Then check the value of p

    $$ p \ge 0 \: then \: result \:  T(n) = \Theta(n^{k} \log^{p} n) $$

    $$
    p < 0 \: then \: result \:  T(n) = \Theta(n^{k})
    $$

Change of variable Method

There are cases where the given recurrence relation does not conform to the general form of recurrence relations, in such cases we can apply the change of variable method in order to solve it using the methods for solving recurrence relation.

You can apply the change of variable method (also called variable substitution) in solving recurrence relations when:

- Non-standard form – The recurrence doesn’t fit directly into the Master Theorem or standard forms Example:$ T(n)=T(n−1)+n. $

- Divide-and-conquer recurrences with unusual terms – When the recurrence has logarithmic or polynomial distortions that prevent direct comparison.Example: $𝑇(𝑛)=2𝑇(\sqrt 𝑛)+𝑛 $ Here, substitution like $𝑛 = 2^𝑚 $ converts it into 𝑇(2𝑚) = 2𝑇(2𝑚/2), which is easier to handle.

- When the variable appears in a non-linear way – Such as square roots, logarithms, or powers. Example: 𝑇(𝑛) =𝑇(𝑛/2)+ log 𝑛. Substitution like $𝑛  =  2^𝑚$, simplifies it to $𝑇(2^𝑚) = 𝑇(2^{𝑚−1})+ 𝑚$

- When recurrence is expressed in terms of functions of 𝑛,like 𝑇(log⁡ 𝑛),$𝑇(𝑛^2)$, etc.

!!! example "Example"

    Say $T(n) = 2T(\sqrt n) + log n $

    let $$ n = 2^m \tag{1} $$

    now = $T(2^m) = 2T(\sqrt {2^m}) + log 2^m $

    $$ \implies T(2^m) = 2T(2^{\frac{m}{2}}) + log 2^m $$

    let $ T(2^m) = S(m) $ then

    $$ \implies S(\frac{m}{2}) = T(2^{\frac{m}{2}}) $$

    $$ \implies S(m) = 2S(\frac{m}{2}) +m \tag{2}$$

    as Seen equation (2) is in a general form of recurrence relation, so we can solve this using master theorem
     where $a=2, b=2$ and $f(m) =m$. on solving it falls in case 2, thus solution is $f(m) = \Theta (m \log m)$
     substituting back in eq(1)

    $$n=2^m$$

    $$\implies m= \log n$$

    therefore
    $$
      \boxed{
            f(n) =\Theta(log log  logn)
      }
    $$
