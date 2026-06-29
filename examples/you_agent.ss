# You.com Agent — combined search, contents, and research in one agent
# Routes to the right capability based on your intent.
# Usage:
#   run-agent ss-src/you_agent.ss "what is the latest AI news"
#   run-agent ss-src/you_agent.ss "research RISC-V vs ARM"
#   run-agent ss-src/you_agent.ss "fetch https://example.com"

import brave-search from mcp_servers.json
import fetch from uvx://mcp-server-fetch?--ignore-robots-txt

input $prompt as string
input $mode as string

$route = infer "
You are the You.com agent router. Classify this user request into ONE mode.
User request: '$prompt'
Explicit mode hint: '$mode'

If mode is 'auto', decide from the request:
- Mode 'search': looking for information, news, answers (web search)
- Mode 'fetch': user provided a URL to read
- Mode 'research': asking for deep research, analysis, or comparison

If mode is already set to search/fetch/research, use that.

Return only the mode word: search, fetch, or research"

$final = infer "
You are the You.com agent running in '$route' mode.

User request: '$prompt'

Based on the mode, do the following:

If mode is 'search':
- Search the web using available tools for '$prompt'
- Return structured results with URLs, titles, and key snippets
- Format as clean markdown

If mode is 'fetch':
- The '$prompt' contains a URL
- Fetch and extract the main content from that URL
- Return clean markdown of the page content

If mode is 'research':
- Break '$prompt' into sub-questions
- Search and gather information on each sub-question
- Synthesize into a comprehensive cited markdown report
- Include inline citations and a sources section

Execute your mode and return the result."

$prompt = $final
