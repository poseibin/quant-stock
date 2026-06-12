package database

import (
	"strings"
	"testing"
)

func TestMySQLSchemaStatementsAreTranslated(t *testing.T) {
	statements := mysqlSchemaStatements()
	if len(statements) == 0 {
		t.Fatal("expected mysql schema statements")
	}
	joined := strings.ToUpper(strings.Join(statements, "\n"))
	for _, bad := range []string{"AUTOINCREMENT", "INSERT OR IGNORE", "CREATE INDEX IF NOT EXISTS", "PRAGMA"} {
		if strings.Contains(joined, bad) {
			t.Fatalf("mysql schema contains unsupported fragment %q", bad)
		}
	}
	if !strings.Contains(joined, "AUTO_INCREMENT") {
		t.Fatal("expected auto increment translation")
	}
}
