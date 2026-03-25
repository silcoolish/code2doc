/**
 * Person interface
 */
interface IPerson {
    name: string;
    age: number;
    greet(): string;
}

/**
 * Person class implementation
 */
class Person implements IPerson {
    constructor(
        public name: string,
        public age: number
    ) {}

    greet(): string {
        return `Hello, my name is ${this.name}`;
    }

    celebrateBirthday(): void {
        this.age++;
    }

    getName(): string {
        return this.name;
    }
}

/**
 * Calculator with generic type
 */
class Calculator<T extends number> {
    private history: T[] = [];

    add(a: T, b: T): T {
        const result = (a + b) as T;
        this.history.push(result);
        return result;
    }

    subtract(a: T, b: T): T {
        const result = (a - b) as T;
        this.history.push(result);
        return result;
    }

    getHistory(): T[] {
        return [...this.history];
    }
}

// Type alias
type Processor<T> = (input: T) => T;

// Standalone function
function processData<T>(data: T[]): T[] {
    return data.filter(item => item !== null);
}

// Arrow function with type annotation
const multiply: (a: number, b: number) => number = (a, b) => a * b;

export { Person, Calculator, processData, multiply };
