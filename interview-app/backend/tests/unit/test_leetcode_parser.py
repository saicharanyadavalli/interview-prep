"""Unit tests for services.leetcode_parser."""

from pathlib import Path
import pytest

from services.leetcode_parser import (
    ParsedApproach,
    ParsedProblem,
    extract_frontmatter,
    extract_qnum_and_title,
    extract_slug,
    extract_difficulty,
    extract_topic_tags,
    extract_description,
    extract_complexity,
    normalize_language,
    parse_leetcode_markdown,
    validate_problem,
)


SAMPLE_TWO_SUM_MD = """---
difficulty: Easy
tags:
    - Array
    - Hash Table
---

<!-- problem:start -->

# [1. Two Sum](https://leetcode.com/problems/two-sum)

[中文文档](/solution/0000-0099/0001.Two%20Sum/README.md)

## Description

<!-- description:start -->

<p>Given an array of integers <code>nums</code> and an integer <code>target</code>, return <em>indices of the two numbers such that they add up to <code>target</code></em>.</p>

<p>You may assume that each input would have <strong><em>exactly</em> one solution</strong>.</p>

<!-- description:end -->

## Solutions

<!-- solution:start -->

### Solution 1: Hash Table

We can use a hash table to store each element and its index.
Traverse the array and look up complements.

Time complexity is $O(n)$, and space complexity is $O(n)$.

<!-- tabs:start -->

#### Python3

```python
class Solution:
    def twoSum(self, nums: List[int], target: int) -> List[int]:
        d = {}
        for i, x in enumerate(nums):
            if (y := target - x) in d:
                return [d[y], i]
            d[x] = i
```

#### Java

```java
class Solution {
    public int[] twoSum(int[] nums, int target) {
        Map<Integer, Integer> d = new HashMap<>();
        return new int[]{};
    }
}
```

#### C++

```cpp
class Solution {
public:
    vector<int> twoSum(vector<int>& nums, int target) {
        return {};
    }
};
```

<!-- tabs:end -->

<!-- solution:end -->
"""

SAMPLE_MULTI_APPROACH_MD = """---
difficulty: Medium
tags:
    - Two Pointers
    - String
---

# [5. Longest Palindromic Substring](https://leetcode.com/problems/longest-palindromic-substring)

## Description

<!-- description:start -->
Find the longest palindromic substring in s.
<!-- description:end -->

## Solutions

### Solution 1: Dynamic Programming

Intuition: Use a 2D table where dp[i][j] indicates whether s[i..j] is a palindrome.

Time complexity is $O(n^2)$, and space complexity is $O(n^2)$.

<!-- tabs:start -->

#### Python3

```python
# DP solution
```

<!-- tabs:end -->

### Solution 2: Expand Around Center

Intuition: Enumerate all 2n-1 possible centers and expand outwards.

Time complexity is $O(n^2)$, and space complexity is $O(1)$.

<!-- tabs:start -->

#### Python3

```python
# Center expansion solution
```

#### Go

```go
// Go solution
```

<!-- tabs:end -->
"""


def test_parse_full_markdown_with_frontmatter():
    """Verify parsing full LeetCode problem with frontmatter, description, and solution tabs."""
    parsed = parse_leetcode_markdown(SAMPLE_TWO_SUM_MD, "0001 - Two Sum.md")
    assert parsed is not None
    assert parsed.qnum == 1
    assert parsed.title == "Two Sum"
    assert parsed.slug == "two-sum"
    assert parsed.difficulty == "Easy"
    assert parsed.topic_tags == ["Array", "Hash Table"]
    assert "Given an array of integers" in parsed.description_md
    assert len(parsed.approaches) == 1

    appr = parsed.approaches[0]
    assert appr.approach_index == 1
    assert appr.title == "Hash Table"
    assert "$O(n)$" in appr.time_complexity
    assert "$O(n)$" in appr.space_complexity
    assert "hash table" in appr.explanation_md

    assert "python" in parsed.code_solutions
    assert "java" in parsed.code_solutions
    assert "cpp" in parsed.code_solutions
    assert "class Solution:" in parsed.code_solutions["python"]


def test_parse_multi_approach_markdown():
    """Verify parsing multiple solution approaches with their complexities and tabs."""
    parsed = parse_leetcode_markdown(SAMPLE_MULTI_APPROACH_MD)
    assert parsed is not None
    assert parsed.qnum == 5
    assert parsed.title == "Longest Palindromic Substring"
    assert parsed.difficulty == "Medium"
    assert len(parsed.approaches) == 2

    app1 = parsed.approaches[0]
    assert app1.approach_index == 1
    assert app1.title == "Dynamic Programming"
    assert "$O(n^2)$" in app1.time_complexity
    assert "$O(n^2)$" in app1.space_complexity
    assert "2D table" in app1.intuition_md

    app2 = parsed.approaches[1]
    assert app2.approach_index == 2
    assert app2.title == "Expand Around Center"
    assert "$O(n^2)$" in app2.time_complexity
    assert "$O(1)$" in app2.space_complexity
    assert "possible centers" in app2.intuition_md

    assert "python" in parsed.code_solutions
    assert "go" in parsed.code_solutions


def test_parse_from_relative_path_format():
    """Verify extracting qnum and title from doocs repository path format."""
    content = """# 1. Two Sum
## Description
Find pairs that sum to target.
## Solutions
```python
def solve(): pass
```
"""
    parsed = parse_leetcode_markdown(
        content, "solution/0000-0099/0001.Two Sum/README_EN.md"
    )
    assert parsed is not None
    assert parsed.qnum == 1
    assert parsed.title == "Two Sum"
    assert parsed.slug == "two-sum"


def test_normalize_language():
    """Verify language headers normalization."""
    assert normalize_language("Python3") == "python"
    assert normalize_language("Python 3") == "python"
    assert normalize_language("Java") == "java"
    assert normalize_language("C++") == "cpp"
    assert normalize_language("TypeScript") == "typescript"
    assert normalize_language("Golang") == "go"
    assert normalize_language("C#") == "csharp"
    assert normalize_language("Rust") == "rust"


def test_description_fallback_without_markers():
    """Verify description is extracted even without description markers."""
    content = """# [42. Trapping Rain Water](https://leetcode.com/problems/trapping-rain-water)

## Description

Given n non-negative integers representing an elevation map.

## Solutions

### Solution 1: Two Pointers
Intuition: Maintain left and right max pointers.
"""
    parsed = parse_leetcode_markdown(content)
    assert parsed is not None
    assert parsed.qnum == 42
    assert parsed.title == "Trapping Rain Water"
    assert "Given n non-negative integers" in parsed.description_md


def test_non_problem_markdown_rejected():
    """Verify general repo READMEs, empty files, or non-problem docs return None."""
    assert parse_leetcode_markdown("") is None
    assert parse_leetcode_markdown("   \n\t  ") is None

    readme = """# LeetCode Solutions Repository
Welcome to the repository containing algorithmic solutions.
## Table of Contents
- Arrays
- Trees
"""
    assert parse_leetcode_markdown(readme) is None


def test_validate_problem():
    """Verify validate_problem invariants and error messaging."""
    # Valid
    p = ParsedProblem(
        qnum=1,
        title="Two Sum",
        slug="two-sum",
        difficulty="Easy",
        description_md="Description",
    )
    valid, err = validate_problem(p)
    assert valid is True
    assert err == ""

    # None
    valid, err = validate_problem(None)
    assert valid is False
    assert "None" in err

    # Invalid qnum
    p.qnum = 0
    valid, err = validate_problem(p)
    assert valid is False
    assert "qnum" in err

    p.qnum = -10
    valid, err = validate_problem(p)
    assert valid is False
    assert "qnum" in err

    # Invalid difficulty
    p.qnum = 1
    p.difficulty = "Expert"
    valid, err = validate_problem(p)
    assert valid is False
    assert "difficulty" in err

    # Empty title
    p.difficulty = "Easy"
    p.title = "   "
    valid, err = validate_problem(p)
    assert valid is False
    assert "title" in err

    # Empty slug
    p.title = "Valid Title"
    p.slug = ""
    valid, err = validate_problem(p)
    assert valid is False
    assert "slug" in err

    # Empty description
    p.slug = "valid-title"
    p.description_md = "   "
    valid, err = validate_problem(p)
    assert valid is False
    assert "description_md" in err


def test_parse_real_leetcode_files_if_present():
    """Smoke test on actual files if directory exists on local disk."""
    p1 = Path(r"C:\Users\yadav\Desktop\learning\leetcode data\solutions\0001 - Two Sum.md")
    if p1.exists():
        parsed = parse_leetcode_markdown(p1.read_text(encoding="utf-8"), p1.name)
        assert parsed is not None
        assert parsed.qnum == 1
        assert parsed.title == "Two Sum"
        assert parsed.difficulty == "Easy"
        assert len(parsed.approaches) >= 1
        assert "python" in parsed.code_solutions
