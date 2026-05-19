function startQuiz(svg, onExit, setQuizActive) {
  const panel = document.getElementById('panel');
  const quizBtn = document.getElementById('quiz-btn');

  const questions = typeof QUIZ_QUESTIONS !== 'undefined' ? QUIZ_QUESTIONS.slice() : [];

  if (questions.length === 0) {
    panel.innerHTML = `
      <span class="tag">QUIZ</span>
      <h2>No questions yet</h2>
      <p>Quiz questions are coming soon. Explore the map for now!</p>
      <button class="scenario-btn" id="quiz-exit-empty">← Back to explore</button>
    `;
    document.getElementById('quiz-exit-empty').addEventListener('click', onExit);
    return;
  }

  // Warn about broken node/arrow references without crashing the quiz
  questions.forEach((q, i) => {
    if (!Array.isArray(q.options) || q.options.length !== 4)
      console.warn(`[Quiz] Q${i + 1}: expected 4 options`);
    if (q.correct < 0 || q.correct > 3)
      console.warn(`[Quiz] Q${i + 1}: correct index out of range`);
    (q.highlightNodes || []).forEach(id => {
      if (!svg.querySelector(`[data-node="${id}"]`))
        console.warn(`[Quiz] Q${i + 1}: node "${id}" not found in SVG`);
    });
    (q.highlightArrows || []).forEach(id => {
      if (!svg.querySelector(`[data-arrow="${id}"]`))
        console.warn(`[Quiz] Q${i + 1}: arrow "${id}" not found in SVG`);
    });
  });

  shuffle(questions);

  let index = 0;
  let score = 0;
  let answered = false;

  function enter() {
    if (setQuizActive) setQuizActive(true);
    if (quizBtn) quizBtn.disabled = true;
  }

  function exit() {
    if (setQuizActive) setQuizActive(false);
    if (quizBtn) quizBtn.disabled = false;
    clearAllStates(svg);
    onExit();
  }

  function render() {
    if (index >= questions.length) {
      renderResults();
      return;
    }
    const q = questions[index];
    clearAllStates(svg);
    dimAll(svg);
    highlightNodes(svg, q.highlightNodes || []);
    animateArrows(svg, q.highlightArrows || []);

    answered = false;
    panel.innerHTML = `
      <div class="quiz-header">
        <span class="tag">QUIZ</span>
        <span class="quiz-progress">Q ${index + 1} / ${questions.length}</span>
        <span class="quiz-score-inline">${score} correct</span>
        <button class="quiz-exit-btn" id="quiz-exit-now" aria-label="Exit quiz">✕ Exit</button>
      </div>
      <p class="quiz-question">${q.question}</p>
      <div class="quiz-options">
        ${q.options.map((opt, i) => `
          <button class="quiz-option" data-index="${i}">${opt}</button>
        `).join('')}
      </div>
      <div class="quiz-feedback" id="quiz-feedback" aria-live="polite"></div>
    `;

    document.getElementById('quiz-exit-now').addEventListener('click', exit);

    const optionBtns = panel.querySelectorAll('.quiz-option');
    optionBtns.forEach(btn => {
      btn.addEventListener('click', () => handleAnswer(parseInt(btn.dataset.index)));
    });
    if (optionBtns.length) optionBtns[0].focus();
  }

  function handleAnswer(chosen) {
    if (answered) return;
    answered = true;

    const q = questions[index];
    const isCorrect = chosen === q.correct;
    if (isCorrect) score++;

    panel.querySelectorAll('.quiz-option').forEach((btn, i) => {
      btn.disabled = true;
      if (i === q.correct) {
        btn.classList.add('correct');
        btn.textContent = '✓ ' + btn.textContent;
      } else if (i === chosen) {
        btn.classList.add('wrong');
        btn.textContent = '✗ ' + btn.textContent;
      }
    });

    document.getElementById('quiz-feedback').innerHTML = `
      <div class="${isCorrect ? 'tip' : 'gotcha'}">
        <strong>${isCorrect ? 'Correct!' : 'Not quite.'}</strong>
        ${q.explanation}
      </div>
      <button class="quiz-next-btn" id="quiz-next">
        ${index + 1 < questions.length ? 'Next question →' : 'See results'}
      </button>
    `;

    const nextBtn = document.getElementById('quiz-next');
    nextBtn.addEventListener('click', () => {
      index++;
      render();
    });
    nextBtn.focus();
  }

  function renderResults() {
    clearAllStates(svg);
    const pct = Math.round((score / questions.length) * 100);
    const msg = pct === 100 ? 'Perfect score!'
              : pct >= 70  ? 'Good work — solid understanding.'
              : pct >= 40  ? 'Getting there. Review the highlighted nodes and try again.'
              :               'Keep exploring the map, then retry.';

    panel.innerHTML = `
      <span class="tag">QUIZ COMPLETE</span>
      <h2 class="quiz-result-score">${score} / ${questions.length} correct</h2>
      <p>${msg}</p>
      <div class="quiz-result-bar">
        <div class="quiz-result-fill" style="width:${pct}%"></div>
      </div>
      <div class="quiz-result-actions">
        <button class="quiz-next-btn" id="quiz-retry">Try again</button>
        <button class="scenario-btn" id="quiz-exit">Back to explore</button>
      </div>
    `;

    document.getElementById('quiz-retry').addEventListener('click', () => {
      shuffle(questions);
      index = 0;
      score = 0;
      render();
    });
    document.getElementById('quiz-exit').addEventListener('click', exit);
  }

  enter();
  render();
}

function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
}
