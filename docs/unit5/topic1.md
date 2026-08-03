# 5.1 Comparison-based Sorting Analysis

These algorithms determine the sorted order by comparing elements. The fundamental operation is the "compare-and-swap."
Examples: Insertion Sort, Selection Sort, Bubble Sort, Merge Sort, Heap Sort, Quick Sort.

## 5.1.1 Review of common comparison-based sorting algorithms

**Simple Sorts:**

1. **Insertion Sort:** Builds the final sorted array one item at a time. It is efficient for ==**_small datasets or nearly sorted data_**==.

2. **Selection Sort:** Repeatedly finds the minimum element from the unsorted part and puts it at the beginning i.e, ==**_minimizes number of swaps_**==

3. **Bubble Sort:** Simplest Comparison based sorting algorithm, Repeatedly steps through the list, compares adjacent elements, and swaps them if they are in the wrong order.

| Algorithm      | Best Case | Average Case | Worst Case | Stable | In-place |
| -------------- | --------- | ------------ | ---------- | ------ | -------- |
| Insertion Sort | O(n)      | O(n²)        | O(n²)      | Yes    | Yes      |
| Selection Sort | O(n²)     | O(n²)        | O(n²)      | No     | Yes      |
| Bubble Sort    | O(n)      | O(n²)        | O(n²)      | Yes    | Yes      |

!!! info "Note"

    Insertion Sort (Best Case O(n)): Occurs when the input is already sorted. Each new element is only compared to its immediate predecessor and immediately placed, leading to n-1 comparisons and 0 swaps.

     Selection Sort (Always Θ(n²)): It always performs ~n²/2 comparisons, regardless of input order, because it must scan the entire unsorted segment to find the minimum each time.

**Efficient Sorts:**

1. **Merge Sort:** A divide-and-conquer algorithm that splits the array in half, recursively sorts each half, and then merges the two sorted halves.

2. **Heap Sort:** Builds a binary max-heap from the input and then repeatedly extracts the maximum element, which gives the items in sorted order.

| Algorithm  | Best Case  | Average Case | Worst Case | Stable | In-place |
| ---------- | ---------- | ------------ | ---------- | ------ | -------- |
| Merge Sort | O(n log n) | O(n log n)   | O(n log n) | Yes    | No       |
| Heap Sort  | O(n log n) | O(n log n)   | O(n log n) | No     | Yes      |

!!! info "Note"

    Merge Sort: The recurrence relation is $T(n) = 2T(n/2) + Θ(n)$. Applying the Master Theorem (Case 2), this solves to Θ(n log n). The linear Θ(n) term comes from the merge operation. The space complexity O(n) is for the temporary array used during merging.

    Heap Sort: Building the heap takes O(n) time. Each of the n extract-max operations takes O(log n) time. Thus, the total is O(n) + O(n log n) = O(n log n).

## 5.1.2 Analysis of Insertion Sort, Selection Sort, and Bubble Sort

## 5.1.3 Analysis of Merge Sort and Heap Sort

## 5.1.4 Comparison of average-case and worst-case performances

## Test Your self

## Reference

[^1]: **_Introduction to the Design and Analysis of Algorithms_** by Anany Levitin
