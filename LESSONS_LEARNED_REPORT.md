# Lessons Learned Report

## Project
**Lipalangoang / Urban Cab Passenger Transportation System**  
A Flask and MySQL web application for booking, tracking, assigning, and reporting rides around Maseru CBD and MSU Local.

## Purpose of the Project
The goal of this project was to build a transport management system that allows:
- Passengers to request rides without creating accounts
- Drivers to accept and complete trips
- Administrators to manage drivers, locations, rides, and reports

This project combined web development, database design, validation, and role-based access control in one system.

## Key Lessons Learned

### 1. Strong database design makes application logic easier
One major lesson was that a clear database structure simplifies the rest of the system. The project uses separate tables for locations, fares, drivers, rides, payment methods, vehicle status, admin users, and reports. Because the entities are separated properly, it became easier to manage relationships, generate summaries, and enforce consistency.

We also learned that database views and stored procedures reduce repeated logic in the application. Views such as ride summaries and demand reports make querying cleaner, while procedures for accepting, starting, completing, and cancelling rides help keep business rules consistent.

### 2. Input validation is essential for reliability
The system accepts data from passengers, drivers, and administrators. This showed how important validation is for names, phone numbers, passwords, license numbers, and route selections. Without validation, the system could easily store incorrect or incomplete information.

The project reinforced that validation should happen in more than one place:
- On the client side for quick feedback
- On the server side for security and correctness
- In the database where needed for long-term integrity

### 3. Role-based access improves security and organization
Another lesson learned was the importance of separating user responsibilities. Public passengers, drivers, and administrators all interact with the same system differently. By controlling access through session checks and role-based routing, the application becomes safer and easier to manage.

This also helped the design of the interface because each user group only sees the actions relevant to them.

### 4. Simplicity can improve usability
Allowing passengers to book rides without creating accounts makes the system faster and more practical for local transport use. This taught us that not every system needs complex onboarding. Sometimes a simple flow solves the real user problem better.

The booking, tracking, and dashboard pages show that small, focused workflows are often more effective than overcrowded screens.

### 5. Real-time style features can be built incrementally
The project includes ride tracking and auto-refresh behavior for drivers. This showed that even without full real-time sockets, it is still possible to create a responsive user experience using simpler techniques such as polling and status endpoints.

This was a useful lesson in balancing ambition with project scope.

### 6. Reporting adds decision-making value
The admin reporting section demonstrated that systems are more useful when they do more than store transactions. Reports help turn ride activity into information that administrators can use for planning, monitoring demand, and evaluating performance.

This taught us that analytics should be considered part of the system design, not just an optional extra.

## Challenges Encountered
- Keeping application logic, database logic, and UI behavior aligned across passenger, driver, and admin workflows
- Ensuring fare calculation works correctly for all routes
- Managing ride status transitions without conflicts
- Maintaining consistent formatting and display of dates, currency, and status values
- Handling text encoding and display issues in some interface files
- Avoiding duplication and confusion caused by multiple copies of similar project files in the workspace

## How the Challenges Were Addressed
- Structured the database carefully and linked tables through foreign keys
- Used helper functions and reusable queries in the Flask application
- Added validation rules before inserting or updating records
- Used views and procedures to centralize repeated operations
- Built separate dashboards for each role to reduce complexity
- Improved report generation and route-based fare lookup to make output more useful

## What Went Well
- The project covers the full workflow from ride request to ride completion
- The system supports multiple user roles successfully
- The database design is detailed enough to support both operations and reporting
- The interface is simple and task-focused
- The project demonstrates practical use of Flask with MySQL in a real-world scenario

## What Could Be Improved
- Password security could be improved further by using stronger password hashing utilities
- Some UI files show character encoding problems that should be cleaned up
- Real-time updates could be improved with WebSockets instead of periodic refresh
- Automated tests should be added for booking, login, status transitions, and reports
- The project structure should be cleaned up so there is only one clear source copy of the application
- Environment secrets should not be kept as defaults inside application code

## Conclusion
This project provided valuable experience in full-stack system development. The most important lesson learned is that successful software depends on balancing three things: a well-designed database, clear application logic, and a simple user experience. The project also showed that practical local solutions can be built effectively with standard web technologies when the system is structured carefully.

Overall, the project was a strong learning experience in database-driven application development, validation, security awareness, workflow design, and reporting.
