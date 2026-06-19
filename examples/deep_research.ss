# Deep Research Engine
# This script is what agent-create would generate from "make a deep research engine".
# Usage:
#   run-agent examples/deep_research.ss "your research topic"
# Or edit $prompt below and:
#   python3 -m ss.cli examples/deep_research.ss

import brave-search from mcp_servers.json

# When run via run-agent, $prompt is set automatically.
# When run directly, set $topic below.
$topic = $prompt

# Step 1: Break the topic into sub-questions
$subquestions = infer "
Given the topic '$topic', generate 4 specific search queries
that would comprehensively cover it. Return them as a JSON list of strings.
"

# Step 2: Search each sub-question
$all_notes = []
for each $query in $subquestions:
    $urls = %brave-search.search $query
    for each $url in $urls:
        $page = %brave-search.fetch $url
        $insight = infer "
From the following page content, extract the single most important
technical insight relevant to '$topic'. Be specific and cite details.
Page: $page
"
        %append $all_notes $insight
    end
end

# Step 3: Synthesize into a structured report
$synthesis = infer "
Synthesize the following research notes into a well-structured markdown report
on '$topic'. Include a summary, key findings, and open questions.
Notes: $all_notes
"

# Step 4: Write the report
%write research_output.md $synthesis
