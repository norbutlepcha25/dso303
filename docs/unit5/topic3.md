# 5.3 Quicksort Analysis and Performance

Quicksort is a divide-and-conquer algorithm.

**Divide:** Choose a pivot element and partition the array so that all elements less than the pivot are to its left, and all elements greater are to its right. The pivot is now in its final sorted position.

**Conquer:** Recursively sort the left and right sub-arrays.

**Combine:** No work is needed, as the array is sorted in place.

<figure markdown="span">
    ![RBS](../img/unit5Sorting/quick_sort_partition_animation.gif){width="100%"}
    <figcaption>Quick sort Algorithm</figcaption>
    <p align='right' style="font-size:0.8em"><i>Image Source: <a href="https://akshitadixit.github.io/Structurex/quickSort.html/"> Strucrex</a ></i></p>
</figure>

**Steps**

**Step 1: Choose a Pivot**

Select an element from the array as the pivot. Common strategies:

- First element
- Last element
- Middle element
- Random element
- Median of three

**Step 2: Partitioning**

Rearrange the array so that:

- All elements less than pivot come before it
- All elements greater than pivot come after it
- The pivot is in its final sorted position

**Step 3: Recursively Sort**

Apply the same process to the sub-arrays on left and right of the pivot.

## 5.3.1 Quicksort algorithm review

```
quicksort(arr, low, high):
    if low < high:
        pivot_index = partition(arr, low, high)
        quicksort(arr, low, pivot_index - 1)
        quicksort(arr, pivot_index + 1, high)
```

```
def partition(arr, low, high):
    pivot = arr[high]
    i = low - 1

    for j in range(low, high):
        if arr[j] <= pivot:
            i += 1
            arr[i], arr[j] = arr[j], arr[i]

    arr[i + 1], arr[high] = arr[high], arr[i + 1]
    return i + 1
```

!!! info "Fun fact"

    Quicksort was developed by **Tony Hoare** in 1960, when he was only 25 years old! Originally developed for machine translation of Russian to English. "I thought it was too simple to be worth publishing" - Hoare.

    It is ***still one of the fastest and most widely used sorting algorithms today*** — used in C standard library (qsort) and Java’s Arrays.sort() (for primitive types).

## 5.3.2 Best-case, average-case, and worst-case analysis

| Case             | Condition                   | Recurrence                    | Time Complexity | Space Complexity |
| ---------------- | --------------------------- | ----------------------------- | --------------- | ---------------- |
| **Best Case**    | Balanced partitions         | ( T(n) = 2T(n/2) + O(n) )     | **O(n log n)**  | O(log n)         |
| **Average Case** | Random pivot                | ( T(n) = T(k)+T(n-k-1)+O(n) ) | **O(n log n)**  | O(log n)         |
| **Worst Case**   | Sorted input with bad pivot | ( T(n) = T(n-1)+O(n) )        | **O(n²)**       | O(n)             |

## 5.3.3 Techniques for choosing good pivots

| Technique              | Description                                     | Pros                                    | Cons                           |
| ---------------------- | ----------------------------------------------- | --------------------------------------- | ------------------------------ |
| **First/Last Element** | Simplest form                                   | Easy to implement                       | Poor if data is already sorted |
| **Random Pivot**       | Choose a random element as pivot                | Avoids worst case with high probability | Needs random number generation |
| **Median-of-Three**    | Take median of first, middle, and last elements | Reduces chance of bad split             | Slightly more computation      |
| **Median of Medians**  | Approximate true median in linear time          | Guarantees O(n log n)                   | Complex to implement           |
| **Hybrid Strategies**  | Switch method based on input size or randomness | Practical                               | Implementation overhead        |

## 5.3.4 Optimizations and variations of Quicksort

| Optimization           | Goal                    | Effect            |
| ---------------------- | ----------------------- | ----------------- |
| Tail Recursion         | Reduce recursion depth  | Less memory       |
| Small-array switch     | Better for small inputs | Faster            |
| Three-way Partitioning | Handle duplicates       | Efficient         |
| Randomization          | Avoid worst-case        | Balanced          |
| Hybrid Sorts           | Guarantee efficiency    | Stable O(n log n) |
