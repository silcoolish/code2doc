package main

import (
	"fmt"
	"strings"
)

// Person represents a person
type Person struct {
	Name string
	Age  int
}

// NewPerson creates a new Person
func NewPerson(name string, age int) *Person {
	return &Person{
		Name: name,
		Age:  age,
	}
}

// Greet returns a greeting message
func (p *Person) Greet() string {
	return fmt.Sprintf("Hello, my name is %s", p.Name)
}

// CelebrateBirthday increments age
func (p *Person) CelebrateBirthday() {
	p.Age++
}

// Calculator performs calculations
type Calculator struct {
	history []float64
}

// NewCalculator creates a new Calculator
func NewCalculator() *Calculator {
	return &Calculator{
		history: make([]float64, 0),
	}
}

// Add adds two numbers
func (c *Calculator) Add(a, b float64) float64 {
	result := a + b
	c.history = append(c.history, result)
	return result
}

// Subtract subtracts b from a
func (c *Calculator) Subtract(a, b float64) float64 {
	result := a - b
	c.history = append(c.history, result)
	return result
}

// GetHistory returns calculation history
func (c *Calculator) GetHistory() []float64 {
	result := make([]float64, len(c.history))
	copy(result, c.history)
	return result
}

// Standalone function
func ProcessData(data []string) []string {
	result := make([]string, len(data))
	for i, item := range data {
		result[i] = strings.ToUpper(item)
	}
	return result
}
