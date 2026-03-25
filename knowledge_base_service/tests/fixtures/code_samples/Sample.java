package com.example.test;

import java.util.List;
import java.util.ArrayList;
import java.util.Optional;

/**
 * A person class for testing.
 */
public class Person {
    private String name;
    private int age;

    public Person(String name, int age) {
        this.name = name;
        this.age = age;
    }

    public String greet() {
        return "Hello, my name is " + name;
    }

    public void celebrateBirthday() {
        age++;
    }

    public String getName() {
        return name;
    }

    public int getAge() {
        return age;
    }
}

/**
 * Calculator class with basic operations.
 */
class Calculator {
    private List<Double> history = new ArrayList<>();

    public double add(double a, double b) {
        double result = a + b;
        history.add(result);
        return result;
    }

    public double subtract(double a, double b) {
        double result = a - b;
        history.add(result);
        return result;
    }

    public List<Double> getHistory() {
        return new ArrayList<>(history);
    }
}

/**
 * Utility interface.
 */
interface Processor<T> {
    T process(T input);
}
