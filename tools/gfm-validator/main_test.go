package main

import (
	"strings"
	"testing"
)

func TestGFMStructures(t *testing.T) {
	source := []byte(`# API Reference

| Name | Type |
| --- | --- |
| id | string |

[Documentation](https://example.com)

![Diagram](diagram.png)

` + "```go\nfmt.Println(\"hello\")\n```\n")

	result, err := validate(source)
	if err != nil {
		t.Fatal(err)
	}

	if !result.Valid {
		t.Fatal("expected valid parse result")
	}

	if result.Headings != 1 ||
		result.Tables != 1 ||
		result.Links != 1 ||
		result.Images != 1 ||
		result.Code != 1 {
		t.Fatalf("unexpected GFM structure: %+v", result)
	}
}

func TestEmptyMarkdown(t *testing.T) {
	for _, input := range []string{"", " ", "\n\t\n"} {
		t.Run(strings.ReplaceAll(input, "\n", "newline"), func(t *testing.T) {
			_, err := validate([]byte(input))
			if err == nil {
				t.Fatal("expected empty Markdown rejection")
			}
		})
	}
}

func TestPlainMarkdown(t *testing.T) {
	result, err := validate([]byte("Ordinary documentation text.\n"))
	if err != nil {
		t.Fatal(err)
	}
	if !result.Valid || result.Nodes == 0 {
		t.Fatalf("unexpected result: %+v", result)
	}
}
