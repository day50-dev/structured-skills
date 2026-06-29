# You.com Contents API — fetch clean markdown content from any URL
# Usage:
#   run-agent ss-src/you_contents.ss "https://example.com/page"
# Or set $urls below and:
#   python3 -m ss.cli ss-src/you_contents.ss

import fetch from uvx://mcp-server-fetch?--ignore-robots-txt

input $urls as string

$url_list = $urls

$parsed_urls = infer "
Parse this into a list of URLs (one per line): $url_list
Return as a JSON array of strings."

$all_content = []

for each $single_url in $parsed_urls:
    $raw = %fetch.fetch url=$single_url max_length=50000
    $page = infer "
You are the You.com Contents API. Extract the main content from this page at $single_url.
Clean up navigation, ads, footers, and boilerplate.
Return as clean markdown with the page title as a heading.
Raw content: $raw
"
    %append $all_content $page
end

$compilation = infer "
You are the You.com Contents API response formatter. Combine these page contents into a single document.
Separate each page with a horizontal rule (---).

Pages: $all_content

Format in clean markdown."

$prompt = $compilation
