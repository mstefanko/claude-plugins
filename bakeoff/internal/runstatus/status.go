package runstatus

const (
	OK                 = "ok"
	OKAfterFormatRetry = "ok_after_format_retry"
	Salvaged           = "salvaged"
	Timeout            = "timeout"
	OutputCap          = "output_cap"
	MissingProvider    = "missing_provider"
	ExitError          = "exit_error"
	SchemaError        = "schema_error"
	Cancelled          = "cancelled"
	ScopeError         = "scope_error"
)
