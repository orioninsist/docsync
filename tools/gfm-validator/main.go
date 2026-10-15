package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/yuin/goldmark"
	"github.com/yuin/goldmark/ast"
	"github.com/yuin/goldmark/extension"
	"github.com/yuin/goldmark/text"
)

type Result struct {
	Valid    bool           `json:"valid"`
	Nodes    int            `json:"nodes"`
	Headings int            `json:"headings"`
	Links    int            `json:"links"`
	Images   int            `json:"images"`
	Tables   int            `json:"tables"`
	Code     int            `json:"code_blocks"`
	Types    map[string]int `json:"node_types"`
}

func validate(source []byte) (Result, error) {
	result := Result{
		Types: make(map[string]int),
	}

	if len(bytes.TrimSpace(source)) == 0 {
		return result, fmt.Errorf("empty Markdown input")
	}

	parser := goldmark.New(
		goldmark.WithExtensions(extension.GFM),
	).Parser()

	document := parser.Parse(text.NewReader(source))

	err := ast.Walk(document, func(node ast.Node, entering bool) (ast.WalkStatus, error) {
		if !entering {
			return ast.WalkContinue, nil
		}

		result.Nodes++
		result.Types[string(node.Kind().String())]++

		switch node.Kind() {
		case ast.KindHeading:
			result.Headings++
		case ast.KindLink:
			result.Links++
		case ast.KindImage:
			result.Images++
		case ast.KindCodeBlock, ast.KindFencedCodeBlock:
			result.Code++
		}

		if node.Kind().String() == "Table" {
			result.Tables++
		}

		return ast.WalkContinue, nil
	})
	if err != nil {
		return result, err
	}

	result.Valid = true
	return result, nil
}

func main() {
	source, err := io.ReadAll(os.Stdin)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	result, err := validate(source)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	if err := json.NewEncoder(os.Stdout).Encode(result); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
