# You.com Research API — multi-step research with cited answers
# Usage:
#   run-agent ss-src/you_research.ss "your research question"
# Or set $question below and:
#   python3 -m ss.cli ss-src/you_research.ss

import brave-search from mcp_servers.json

input $question as string
input $research_effort as string

$topic = $question

$subquestions = infer "
You are the You.com Research API. Break this question into specific sub-questions
that would comprehensively cover it at effort level '$research_effort'.

For 'quick' effort: 2 sub-questions
For 'standard' effort: 4 sub-questions
For 'deep' effort: 6 sub-questions

Question: '$topic'
Return as a JSON array of strings."

$all_notes = []
$source_num = 1

for each $subq in $subquestions:
    $results = %brave-search.search query=$subq count=3
    for each $url in $results:
        $page = %brave-search.fetch $url
        $note = infer "
Extract key facts, data points, and claims from this page relevant to '$topic'.
Note specific numbers, dates, and attributions.
Source URL: $url
Page: $page
"
        %append $all_notes "Source [[$source_num]]: $note (URL: $url)"
        $source_num = %add $source_num 1
    end
end

$report = infer "
You are the You.com Research API. Synthesize the following research notes into a
well-structured markdown report on '$topic'.

Research effort used: $research_effort

Research notes with inline source citations:
$all_notes

Write a comprehensive markdown report with:
1. Executive Summary
2. Key Findings (with inline citations like [[1]], [[2]] etc.)
3. Detailed Analysis organized by theme
4. Open Questions
5. Sources (numbered list with URLs)

Every factual claim must have an inline citation. Be thorough and precise."

$prompt = $report

output $report as file: research_output.md
%write research_output.md $report
