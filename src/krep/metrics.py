from prometheus_client import Counter

SEARCH_ZERO_RESULTS = Counter(
    "search_zero_results",
    "Searches with a query that returned no results on the first page",
    ["tenant"],
)
