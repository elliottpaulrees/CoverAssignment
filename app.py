from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from datetime import date
import datetime
from flask import session
from sqlalchemy import or_


app = Flask(__name__)
app.teachers = None
app.secret_key = 'your-very-secret-key'


#connect to the database
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+mysqlconnector://invigilationdb_loudatomup:2579baed22025cc45c8a56340c85426b33b4d69b@v5wu1.h.filess.io:61002/invigilationdb_loudatomup'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


@app.route('/')
def home():
    app.teachers = teacher.query.all()
        # Get cover counts in a single query
    cover_counts = dict(
        db.session.query(covers.CoverTeacherCode, db.func.count(covers.CoverID))
        .group_by(covers.CoverTeacherCode)
        .all()
    )
    # Assign cover counts to each teacher
    for t in app.teachers:
        t.cover_count = cover_counts.get(t.TeacherCode, 0)

    return render_template('cover_assignments.html', teachers=app.teachers, current_date=date.today().isoformat())

@app.route('/test_connection')
def test_connection():
    try:
        with db.engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        return "Database connection is valid!"
    except Exception as e:
        return f"Database connection failed: {str(e)}"
    
class teacher(db.Model):
    __tablename__ = 'teachers'
    TeacherCode = db.Column(db.String(10), primary_key=True)
    FirstName = db.Column(db.String(50))
    LastName = db.Column(db.String(50))
    Role = db.Column(db.String(50))
    lessonCount = db.Column(db.Integer)
    cover_count = 0

class covers(db.Model):
    __tablename__ = 'covers'
    CoverID = db.Column(db.Integer, primary_key=True)
    CoverTeacherCode = db.Column(db.String(10), db.ForeignKey('teachers.TeacherCode'))
    AbsentTeacherCode = db.Column(db.String(10))
    Date = db.Column(db.Date)
    Period = db.Column(db.String(10))
    Class = db.Column(db.String(50))
    Week = db.Column(db.String(1))
    
class lessonsWeekA(db.Model):
    __tablename__ = 'lessonsweeka'
    LessonID = db.Column(db.Integer, primary_key=True)
    TeacherCode = db.Column(db.String(50), db.ForeignKey('teachers.TeacherCode'))
    Subject = db.Column(db.String(50))
    Class = db.Column(db.String(50))
    Day = db.Column(db.String(50))
    Period = db.Column(db.String(50))
    Room = db.Column(db.String(50))

class lessonsWeekB(db.Model):
    __tablename__ = 'lessonsweekb'
    LessonID = db.Column(db.Integer, primary_key=True)
    TeacherCode = db.Column(db.String(50), db.ForeignKey('teachers.TeacherCode'))
    Subject = db.Column(db.String(50))
    Class = db.Column(db.String(50))
    Day = db.Column(db.String(50))
    Period = db.Column(db.String(50))
    Room = db.Column(db.String(50))

@app.route('/mark_absent', methods=['POST'])
def mark_absent():
    selected_date = request.form.get('absence_date')
    selected_teachers = request.form.getlist('selected_teachers')
    week = request.form.get('week')
    exam_period = request.form.get('exam_period') 

    date_obj = datetime.datetime.strptime(selected_date, "%Y-%m-%d")
    day_of_week = date_obj.strftime("%A")  # 'Monday', 'Tuesday', etc.

    assigned_teachers_today = set()

    # Get all the lessons which require covering based on the week
    if week == 'A':
        lessons = lessonsWeekA.query.filter(
            lessonsWeekA.TeacherCode.in_(selected_teachers),
            lessonsWeekA.Day == day_of_week,
            lessonsWeekA.Class != "free",
            lessonsWeekA.Period != "Reg"
        ).all()
    else:
        lessons = lessonsWeekB.query.filter(
            lessonsWeekB.TeacherCode.in_(selected_teachers),
            lessonsWeekB.Day == day_of_week,
            lessonsWeekB.Class != "free",
            lessonsWeekB.Period != "Reg"
        ).all()

    coverSuggestions = []
    # Creates a 2D array: Each array is a list of teachers for each of the cover lessons in lessons.
    for lesson in lessons:
        free_periods = getCoverTeachers(day_of_week, lesson, week, exam_period)
        
        # Sort all teachers by score
        sorted_teachers = sort_teachers_by_availability(free_periods)

        # Separate into unassigned and already-assigned for today
        unassigned = [t for t in sorted_teachers if t.TeacherCode not in assigned_teachers_today]
        assigned = [t for t in sorted_teachers if t.TeacherCode in assigned_teachers_today]

        # Combine so unassigned come first (most suitable one at top)
        reordered_teachers = unassigned + assigned

        # Add the first teacher (if any) to the assigned set
        if reordered_teachers:
            assigned_teachers_today.add(reordered_teachers[0].TeacherCode)

        coverSuggestions.append((lesson, reordered_teachers))

    # Return to the template with cover suggestions and lessons data
    return render_template('Output.html', 
                           teachers=app.teachers, 
                           coverSuggestions=coverSuggestions, 
                           current_date=selected_date)


def score_teacher(t):
    role = t.Role.lower()
    if "senior" in role:
        expected = 29
    elif "middle" in role:
        expected = 40.6
    else:
        expected = 58

    expected = expected if expected else 1  # Avoid divide by zero
    lesson_ratio = t.lessonCount / expected
    return lesson_ratio + (t.cover_count * 0.05)

def sort_teachers_by_availability(teachers):
    print("Pre-sorted:")
    print(teachers)
    sortedTeachers = sorted(teachers, key=score_teacher)
    print("Post-sorted:")
    print(sortedTeachers)
    return sortedTeachers

def getCoverTeachers(day_of_week, lesson, week, exam_period):
    if week == 'A':
        free_periods = lessonsWeekA.query.filter(
            lessonsWeekA.Day == day_of_week,
            lessonsWeekA.Period == lesson.Period
        ).all()
    else:
        free_periods = lessonsWeekB.query.filter(
            lessonsWeekB.Day == day_of_week,
            lessonsWeekB.Period == lesson.Period
        ).all()

    # Extract eligible teacher codes based on class condition
    eligible_codes = [
        l.TeacherCode for l in free_periods if
        l.Class == "free" or (
            exam_period == "yes" and ("Y11" in l.Class or "Y13" in l.Class)
        )
    ]

    # Return full teacher objects
    return [t for t in app.teachers if t.TeacherCode in eligible_codes]

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

