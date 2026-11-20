use super::*;
use pretty_assertions::assert_eq;
use ratatui::Terminal;
use ratatui::backend::TestBackend;
use tokio::sync::mpsc::unbounded_channel;

fn composer() -> ChatComposer {
    let (tx, _rx) = unbounded_channel::<AppEvent>();
    ChatComposer::new(
        /*has_input_focus*/ true,
        AppEventSender::new(tx),
        /*enhanced_keys_supported*/ false,
        "Ask Codex to do anything".to_string(),
        /*disable_paste_burst*/ false,
    )
}

fn key(code: KeyCode) -> KeyEvent {
    KeyEvent::new(code, KeyModifiers::NONE)
}

#[test]
fn escape_dismisses_slash_popup_until_input_changes() {
    let mut composer = composer();
    composer.set_text_content("/".to_string(), Vec::new(), Vec::new());
    composer.move_cursor_to_end();
    assert!(matches!(composer.active_popup, ActivePopup::Command(_)));

    assert_eq!(
        composer.handle_key_event(key(KeyCode::Esc)),
        (InputResult::None, true)
    );
    assert!(matches!(composer.active_popup, ActivePopup::None));
    assert_eq!(composer.textarea.text(), "/");
    assert_eq!(composer.footer_mode, FooterMode::EscHint);

    composer.sync_popups();
    assert!(matches!(composer.active_popup, ActivePopup::None));

    let mut terminal =
        Terminal::new(TestBackend::new(/*width*/ 60, /*height*/ 8)).expect("test terminal");
    terminal
        .draw(|frame| composer.render(frame.area(), frame.buffer_mut()))
        .expect("render dismissed popup");
    insta::assert_snapshot!("slash_popup_dismissed_on_escape", terminal.backend());

    composer.insert_str("m");
    assert_eq!(composer.textarea.text(), "/m");
    assert!(matches!(composer.active_popup, ActivePopup::Command(_)));

    composer.set_text_content(String::new(), Vec::new(), Vec::new());
    composer.set_text_content("/".to_string(), Vec::new(), Vec::new());
    assert!(matches!(composer.active_popup, ActivePopup::Command(_)));
}

#[test]
fn escape_dismisses_slash_popup_with_footer_modes() {
    for (mode, task_running) in [
        (FooterMode::ShortcutOverlay, false),
        (FooterMode::EscHint, false),
        (FooterMode::ComposerHasDraft, true),
    ] {
        let mut composer = composer();
        composer.set_text_content("/".to_string(), Vec::new(), Vec::new());
        composer.footer_mode = mode;
        composer.set_task_running(task_running);

        assert_eq!(
            composer.handle_key_event(key(KeyCode::Esc)),
            (InputResult::None, true)
        );
        assert!(matches!(composer.active_popup, ActivePopup::None));
        assert_eq!(composer.textarea.text(), "/");
        assert_eq!(
            composer.footer_mode,
            if task_running {
                mode
            } else {
                FooterMode::EscHint
            }
        );
    }
}

#[test]
fn slash_navigation_and_selection_still_work() {
    let mut composer = composer();
    composer.set_text_content("/".to_string(), Vec::new(), Vec::new());
    let ActivePopup::Command(popup) = &composer.active_popup else {
        panic!("slash popup did not open");
    };
    let initial = popup.selected_item();

    composer.handle_key_event(key(KeyCode::Down));
    let ActivePopup::Command(popup) = &composer.active_popup else {
        panic!("slash popup closed during navigation");
    };
    assert_ne!(popup.selected_item(), initial);
    composer.handle_key_event(key(KeyCode::Up));
    let ActivePopup::Command(popup) = &composer.active_popup else {
        panic!("slash popup closed during navigation");
    };
    assert_eq!(popup.selected_item(), initial);

    composer.set_text_content("/mo".to_string(), Vec::new(), Vec::new());
    assert_eq!(
        composer.handle_key_event(key(KeyCode::Tab)),
        (InputResult::None, true)
    );
    assert_eq!(composer.textarea.text(), "/model ");

    composer.set_text_content("/mo".to_string(), Vec::new(), Vec::new());
    assert_eq!(
        composer.handle_key_event(key(KeyCode::Enter)),
        (InputResult::Command(SlashCommand::Model), true)
    );
}

#[test]
fn file_popup_keeps_its_existing_escape_behavior() {
    let mut composer = composer();
    let text = "npx -y @kaeawc/auto-mobile@latest";
    composer.set_text_content(text.to_string(), Vec::new(), Vec::new());
    composer.move_cursor_to_end();
    assert!(matches!(composer.active_popup, ActivePopup::File(_)));

    composer.handle_key_event(key(KeyCode::Esc));
    assert!(matches!(composer.active_popup, ActivePopup::File(_)));
    composer.handle_key_event(key(KeyCode::Esc));
    assert!(matches!(composer.active_popup, ActivePopup::None));
    assert_eq!(composer.textarea.text(), text);
    composer.sync_popups();
    assert!(matches!(composer.active_popup, ActivePopup::None));
}
