# You.com Search API — structured web search with LLM-optimized results
# Usage:
#   run-agent ss-src/you_search.ss "your search query"
# Or set $query below and:
#   python3 -m ss.cli ss-src/you_search.ss

import brave-search from mcp_servers.json

input $query as string

$count = 5
$topic = $query

$raw = %brave-search.search query=$topic count=$count

$structured = infer "
You are the You.com Search API. Given these raw search results for '$topic':
$raw

Return a structured JSON response with the following format:
{
  \"results\": {
    \"web\": [
      {
        \"url\": \"...\",
        \"title\": \"...\",
        \"description\": \"...\",
        \"snippets\": [\"relevant excerpt\", \"another excerpt\"],
        \"page_age\": \"...\",
        \"authors\": [\"...\"]
      }
    ]
  },
  \"metadata\": {
    \"query\": \"$topic\",
    \"total_results\": <count>
  }
}

Extract real URLs, titles, and meaningful snippets from the results. Return ONLY valid JSON."

$answer = infer "
You are the You.com Search API response formatter. Based on these structured search results:
$structured

For the query '$topic', write a concise answer. For each relevant result:
- Include the title, URL, and key snippet
- Group them logically
- Note publication dates where available

Format in clean markdown. Do not make up information not found in the results."

$prompt = $answer
