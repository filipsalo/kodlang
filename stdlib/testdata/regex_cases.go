// Writes stdlib/testdata/regex_cases.jsonl, which stdlib/regex_test.kod
// checks: for each pattern and text, what Go's regexp (RE2's syntax and
// leftmost-first matching, which stdlib/regex.kod follows) makes of it. Run
// from the repository root:
//
//	go run stdlib/testdata/regex_cases.go > stdlib/testdata/regex_cases.jsonl
//
// A pattern Go rejects is written once, with the first text. Each line is
// {"p", "t", "m": every match's group spans, "r": the text with "<$1|${0}>"
// put for each match, "s": the split} or {"p", "t", "err": true}.
//go:build ignore

package main

import (
	"encoding/json"
	"fmt"
	"regexp"
)

var patterns = []string{
	"",
	"a",
	"abc",
	".",
	"..",
	"a*",
	"a+",
	"a?",
	"a*?",
	"a+?",
	"a??",
	"ab*",
	"(ab)*",
	"(ab)+",
	"(a|b)*",
	"(a|ab)(c|bcd)(d*)",
	"a|b|c",
	"ab|a",
	"a|ab",
	"(a*)*",
	"(a*)+",
	"(a|)*",
	"(|a)*",
	"(a*|b)*",
	"x*",
	"^",
	"$",
	"^a",
	"a$",
	"^$",
	"(?m)^",
	"(?m)$",
	"(?m)^\\w+$",
	"^\\w+$",
	"\\b",
	"\\B",
	"\\bfoo\\b",
	"\\Bo",
	"\\d+",
	"\\D+",
	"\\w+",
	"\\W+",
	"\\s+",
	"\\S+",
	"[abc]+",
	"[^abc]+",
	"[a-z]+",
	"[^a-z]+",
	"[a-c-]+",
	"[-a]+",
	"[]a]+",
	"[^]a]+",
	"[\\d.]+",
	"[\\w-]+",
	"[^\\s]+",
	"[\\D]+",
	"(?i)abc",
	"(?i)[a-c]+",
	"(?i:A)b",
	"a(?i)b",
	"(?i)a(?-i)b",
	"(?s).+",
	".+",
	"(?s:.)",
	"a{2}",
	"a{2,}",
	"a{2,3}",
	"a{0,1}",
	"a{,2}",
	"a{2",
	"a{3}?",
	"a{2,}?",
	"(\\d{4})-(\\d{2})-(\\d{2})",
	"(?P<y>\\d{4})-(?P<m>\\d{2})",
	"(?<w>\\w+)",
	"(?:ab)+",
	"(a)(b)?",
	"(a)|(b)",
	"((a)|b)+",
	"(a(b)?)+",
	"é+",
	"[é]+",
	"[^é]+",
	".é",
	"caf.",
	"\\x41",
	"\\x{e9}",
	"[\\x{e9}a]+",
	"\\.",
	"\\*",
	"a\\+",
	"\\(",
	"\\[x\\]",
	"\\{",
	"😀",
	".😀",
	"s+",
	"ss",
	"i(ss)?",
	"(i|s)+",
	"[aeiou]",
	"\\n",
	"\\t",
	"x\\ny",
	"(?m)y$",
	"z\\n$",
	"\\Aa",
	"a\\z",
	"\\A",
	"\\z",
	"(",
	")",
	"a)",
	"(?P<n>a)(?P<n>b)",
	"a**",
	"*",
	"+a",
	"[z-a]",
	"[a",
	"\\",
	"a\\",
	"\\q",
	"(?x)",
	"(?P<>a)",
	"a{1001}",
	"a{3,2}",
	"\\8",
	"[[]",
	"(?i",
	"a|*",
	"x{2}{3}",
	"(?:)",
	"()",
	"(|)",
	"(?:)*",
	"()*",
	"a(?:)b",
	"\\bx\\b",
	"(\\w)(\\w)?",
}

var texts = []string{
	"",
	"abc",
	"aaa",
	"foo food foo",
	"x\ny\nz\n",
	"a1b22c333",
	"AbC aBc ABC",
	"é café naïve",
	"2026-11-27 and 1999-01-02",
	"a.b*c+d?",
}

type result struct {
	P   string   `json:"p"`
	T   string   `json:"t"`
	M   [][]int  `json:"m"`
	Err bool     `json:"err,omitempty"`
	R   string   `json:"r,omitempty"`
	S   []string `json:"s"`
}

func main() {
	for _, p := range patterns {
		re, err := regexp.Compile(p)
		for _, t := range texts {
			r := result{P: p, T: t, M: [][]int{}, S: []string{}}
			if err != nil {
				r.Err = true
			} else {
				r.M = append(r.M, re.FindAllStringSubmatchIndex(t, -1)...)
				r.R = re.ReplaceAllString(t, "<$1|${0}>")
				r.S = re.Split(t, -1)
			}
			b, _ := json.Marshal(r)
			fmt.Println(string(b))
			if err != nil {
				break
			}
		}
	}
}
