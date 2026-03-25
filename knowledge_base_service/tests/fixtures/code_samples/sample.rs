//! Sample Rust module for testing tree-sitter parser

use std::collections::HashMap;

/// A person struct
pub struct Person {
    name: String,
    age: u32,
}

impl Person {
    /// Create a new Person
    pub fn new(name: &str, age: u32) -> Self {
        Self {
            name: name.to_string(),
            age,
        }
    }

    /// Get a greeting message
    pub fn greet(&self) -> String {
        format!("Hello, my name is {}", self.name)
    }

    /// Celebrate birthday
    pub fn celebrate_birthday(&mut self) {
        self.age += 1;
    }

    /// Get name
    pub fn get_name(&self) -> &str {
        &self.name
    }

    /// Get age
    pub fn get_age(&self) -> u32 {
        self.age
    }
}

/// Calculator struct
pub struct Calculator {
    history: Vec<f64>,
}

impl Calculator {
    /// Create a new Calculator
    pub fn new() -> Self {
        Self {
            history: Vec::new(),
        }
    }

    /// Add two numbers
    pub fn add(&mut self, a: f64, b: f64) -> f64 {
        let result = a + b;
        self.history.push(result);
        result
    }

    /// Subtract b from a
    pub fn subtract(&mut self, a: f64, b: f64) -> f64 {
        let result = a - b;
        self.history.push(result);
        result
    }

    /// Get calculation history
    pub fn get_history(&self) -> &[f64] {
        &self.history
    }
}

impl Default for Calculator {
    fn default() -> Self {
        Self::new()
    }
}

/// Standalone function
pub fn process_data(data: &[String]) -> Vec<String> {
    data.iter()
        .map(|s| s.to_uppercase())
        .collect()
}

/// Generic function
pub fn identity<T>(value: T) -> T {
    value
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_person() {
        let person = Person::new("Alice", 30);
        assert_eq!(person.get_age(), 30);
    }
}
