package output

import (
	"fmt"
	"io"
)

type Streams struct {
	Out io.Writer
	Err io.Writer
}

func NewStreams(out io.Writer, err io.Writer) Streams {
	return Streams{Out: out, Err: err}
}

func (s Streams) Printf(format string, args ...any) {
	fmt.Fprintf(s.Out, format, args...)
}

func (s Streams) Errorf(format string, args ...any) {
	fmt.Fprintf(s.Err, format, args...)
}
