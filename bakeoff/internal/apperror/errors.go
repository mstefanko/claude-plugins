package apperror

import (
	"errors"
	"fmt"
)

type UsageError struct {
	Message string
	Err     error
}

func (e *UsageError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	if e.Err != nil {
		return e.Err.Error()
	}
	return "usage error"
}

func (e *UsageError) Unwrap() error {
	return e.Err
}

type ValidationError struct {
	Message string
	Err     error
}

func (e *ValidationError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	if e.Err != nil {
		return e.Err.Error()
	}
	return "validation error"
}

func (e *ValidationError) Unwrap() error {
	return e.Err
}

type RuntimeError struct {
	Message string
	Err     error
}

func (e *RuntimeError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	if e.Err != nil {
		return e.Err.Error()
	}
	return "runtime error"
}

func (e *RuntimeError) Unwrap() error {
	return e.Err
}

type SilentError struct {
	Err error
}

func (e *SilentError) Error() string {
	if e.Err != nil {
		return e.Err.Error()
	}
	return "silent error"
}

func (e *SilentError) Unwrap() error {
	return e.Err
}

type JudgeDisagreementError struct {
	Message string
	Err     error
}

func (e *JudgeDisagreementError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	if e.Err != nil {
		return e.Err.Error()
	}
	return "judge disagreement"
}

func (e *JudgeDisagreementError) Unwrap() error {
	return e.Err
}

type DecisionIncompleteError struct {
	Message string
	Err     error
}

func (e *DecisionIncompleteError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	if e.Err != nil {
		return e.Err.Error()
	}
	return "decision incomplete"
}

func (e *DecisionIncompleteError) Unwrap() error {
	return e.Err
}

type InterruptedError struct {
	Err error
}

func (e *InterruptedError) Error() string {
	if e.Err != nil {
		return e.Err.Error()
	}
	return "interrupted"
}

func (e *InterruptedError) Unwrap() error {
	return e.Err
}

func Usagef(format string, args ...any) error {
	return &UsageError{Message: fmt.Sprintf(format, args...)}
}

func Validationf(format string, args ...any) error {
	return &ValidationError{Message: fmt.Sprintf(format, args...)}
}

func Runtimef(format string, args ...any) error {
	return &RuntimeError{Message: fmt.Sprintf(format, args...)}
}

func IsSilent(err error) bool {
	var target *SilentError
	return errors.As(err, &target)
}
