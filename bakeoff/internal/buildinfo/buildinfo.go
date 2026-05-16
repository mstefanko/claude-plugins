package buildinfo

type Info struct {
	Version string
	Commit  string
	Date    string
}

var (
	Version = "0.0.0"
	Commit  = "unknown"
	Date    = "unknown"
)

func Current() Info {
	return Info{
		Version: Version,
		Commit:  Commit,
		Date:    Date,
	}
}
