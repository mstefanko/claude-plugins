package runner

import (
	"context"

	"golang.org/x/sync/errgroup"
)

func NewGroup(ctx context.Context) (*errgroup.Group, context.Context) {
	return errgroup.WithContext(ctx)
}
