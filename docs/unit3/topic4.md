# Substitution Method

It is a method used to solve a recurrence relation by proving the guessed form of the relation.

The substitution method for solving recurrences comprises two steps:

1. Guess the form of the solution.
2. Use mathematical induction to find the constants and show that the solutionworks.
   We substitute the guessed solution for the function when applying the inductive hypothesis to smaller values; hence the name “substitution method.”

!!! example "Example 1"

    !!! info inline end "Note: General guess"
        - For divide-and-conquer recurrences = 𝑇(𝑛)=𝑂(𝑛log⁡𝑛).
        - For simple ones like 𝑇(𝑛)=𝑇(𝑛−1)+𝑛,  guess a polynomial.
      - step 1: Given recurrence relation
             $\quad T(n)=2T(\frac{n}{2})+n, \quad T(1) =1 $

      - step 2: Making a informed guess ( say using iterative or recursion tree)
            $$ T(n) = \Theta (n\log n) $$

      Testing the basis:

      We’ll try to prove that the guess for upper bound T(n)=O(nlog⁡n) is true for all cases using induction method

      By definition : $ T(n) ≤ c(nlogn) \quad for \quad Ǝ c > 0, ∀n > n0 $

      Basis : for $ n = 1, \newline T(1) ≤ c(1log1) : fails, \therefore n > 1 $

      Basis : for $ n = 2 \newline
      T(2) ≤ c(2log2) \newline
      4 ≤ 2c  $

      Therefore we need value of c >2 and n>1
      So we can conclude that the eq 1 hold true for all value of n ≥ 2,
      i.e 2, 3, 4 ,.... Kth term

      - step 3: Inductive Hypothesis

      Assuming n = k for all value of $ 2 ≤ k ≤ n $
    $$ T(k) ≤ c(klogk)  $$

    It implies that the condition would hold true for $ k = n/2 $
    	$$ T(\frac{n}{2}) ≤ c(\frac{n}{2} \log \frac{n}{2}) $$

      - step 4: Substitute it back
      $$ Thus, \quad T(n) = 2T(\frac{n}{2}) + n \newline $$
    	$$≤ 2 (c(\frac{n}{2} \log \frac{n}{2}))  + n          $$
    	$$ ≤ cn (\log \frac{n}{2})  + n         $$
      $$ ≤ cn (\log n - 1) + n $$
      $$ ≤ cn log n + n (1 - C) $$
      $$ \approx T(n) = \Theta( n \log n ) $$
      Hence proved

#### Try this Question

<!-- Question 1 -->

??? question " Q1. $ \quad T(n) = 2T(n-1)+1, \quad T(1) = 1 $ "

      - step 1: Given recurrence relation
      $$ \quad T(n) = 2T(n-1)+1, \quad T(1) = 1 $$

      - step 2 : Guessing a solution
      $$ T(n)=2^n - 1 $$

          for upper bound $ T(n) ≤ \Theta (2^n - 1) $


          Basis for n = 1
          $$ T(1) ≤ C(1), Holds True$$

          So we can conclude that the eq 1 hold true for all value of n ≥ 1,
          i.e 1, 2, 3, 4 ,.... Kth term


      - step 3 : Inductive Hypothesis

        Assuming n  ≥ k for all values 1 ≤ k ≤ n
    				$$ T(k) ≤ c(2^k - 1) $$

        Therefore $ K= n-1 $ should also hold true
    				$$ T(n-1) ≤ c(2^{n-1} - 1) $$

        Thus, $$T(n) = 2T(n-1) + 1 $$
    		      $$ ≤ 2 (c(2^{n-1} - 1)) + 1 $$
    		      $$ ≤ 2c2^{n-1} - 2  + 1 $$
                  $$ ≤ c2^n - 1 $$
                  Hence proved

<!-- Question 2 -->

??? question " Q1. $ \quad T(n) = T(n-1)+n, \quad T(1) = 1 $ "

      - step 1: Given recurrence relation
      $$ \quad T(n) = T(n-1)+n, \quad T(1) = 1 $$

      - step 2 : Guessing a solution
      $$ T(n)=\Theta (n^2) $$

          for upper bound $ T(n) ≤ c (n^2)$


          Basis for n = 1
          $$ T(1) ≤ C(1), Holds True$$

          So we can conclude that the eq 1 hold true for all value of n ≥ 1,
          i.e 1, 2, 3, 4 ,.... Kth term


      - step 3 : Inductive Hypothesis

        Assuming n  ≥ k for all values 1 ≤ k ≤ n
    				$$ T(k) ≤ c(k^2) $$

        Therefore $ K= n-1 $ should also hold true
    				$$ T(n-1) ≤ c((n-1)^2) $$

        Thus, $$T(n) = T(n-1) + n $$
    		      $$ ≤ c((n-1)^{2}) + n $$
    		      $$ ≤ c(n^2 - 2n + 1)  + n $$
                  $$ ≤ cn^2 - 2cn + c +n  $$
                  Hence proved

         OR futher checking
         We want to show $ 𝑇(𝑛)≤𝑐𝑛^2 $

         That means checking if:
          $$ 𝑐𝑛^2−2𝑐𝑛+𝑐+𝑛  ≤   𝑐𝑛^2  $$

         Cancel $ 𝑐𝑛^2 $ on both sides:

         $$ −2𝑐𝑛+𝑐+𝑛  ≤   0 $$
         $$ n(1-2c)+c ≤  0 $$

         If we choose $ 𝑐 ≥ 1 $ then $ n(1-2c) ≤ -1 $ so the inequality holds for all sufficiently large values
