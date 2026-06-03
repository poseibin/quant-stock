package result

type Artifact struct {
	Name    string           `json:"name"`
	Type    string           `json:"type"`
	Columns []string         `json:"columns"`
	Rows    []map[string]any `json:"rows"`
}
