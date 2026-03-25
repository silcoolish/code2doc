/**
 * Person class for testing
 */
class Person {
    constructor(name, age) {
        this.name = name;
        this.age = age;
    }

    greet() {
        return `Hello, my name is ${this.name}`;
    }

    celebrateBirthday() {
        this.age++;
    }

    getName() {
        return this.name;
    }
}

/**
 * Calculator class with operations
 */
class Calculator {
    constructor() {
        this.history = [];
    }

    add(a, b) {
        const result = a + b;
        this.history.push(result);
        return result;
    }

    subtract(a, b) {
        const result = a - b;
        this.history.push(result);
        return result;
    }

    getHistory() {
        return [...this.history];
    }
}

// Standalone function
function standaloneFunction(x) {
    return x * 2;
}

// Arrow function
const processData = (data) => {
    if (!data) return [];
    return data.map(item => item.toUpperCase());
};

module.exports = { Person, Calculator, standaloneFunction, processData };
