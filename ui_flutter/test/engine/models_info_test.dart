import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/models_info.dart';

const sample = {
  'pc': {
    'ram_gb': 15.7,
    'cores': 8,
    'threads': 16,
    'avx2': true,
    'avx512_vnni': false,
    'gpu': 'Intel Iris Xe',
    'vram_gb': 0.1,
    'directml': false,
    'disk_free_gb': 120.5,
    'ssd': true,
  },
  'tier_recommended': 'balanced',
  'tier_current': 'custom',
  'models': [
    {
      'id': 'minilm',
      'feature': 'text',
      'name': 'all-MiniLM-L6-v2',
      'tier': 'light',
      'licence': 'Apache-2.0',
      'source': 'Hugging Face',
      'size_mb': 23,
      'ram_mb': 90,
      'speed_note': 'Fast on any PC',
      'languages': ['English'],
      'improves': 'Search by meaning',
      'builtin': false,
      'state': 'active',
      'capable': true,
      'capable_reason': '',
      'recommended': false,
    },
    {
      'id': 'e5-base',
      'feature': 'text',
      'name': 'multilingual-e5-base',
      'tier': 'best',
      'licence': 'MIT',
      'source': 'Hugging Face',
      'size_mb': 280,
      'ram_mb': 700,
      'speed_note': 'Slower',
      'languages': ['100+'],
      'improves': 'Meaning in many languages',
      'builtin': false,
      'state': 'not_downloaded',
      'capable': false,
      'capable_reason': 'Needs 16 GB of memory',
      'recommended': false,
    },
    {
      'id': 'winocr',
      'feature': 'ocr',
      'name': 'Windows OCR',
      'tier': 'light',
      'licence': 'Windows',
      'source': 'Windows',
      'size_mb': 0,
      'ram_mb': 0,
      'speed_note': '',
      'languages': [],
      'improves': 'Words in pictures',
      'builtin': true,
      'state': 'ready',
      'capable': true,
      'capable_reason': '',
      'recommended': true,
    },
    'junk',
  ],
};

void main() {
  test('the models answer: the PC, the tiers, every model with its facts', () {
    final m = ModelsInfo.fromJson(sample);
    expect(m.pc!.threads, 16);
    expect(m.tierRecommended, 'balanced');
    expect(m.tierCurrent, 'custom');
    expect(m.models, hasLength(3));
    final e5 = m.models[1];
    expect(e5.capable, isFalse);
    expect(e5.capableReason, 'Needs 16 GB of memory');
    expect(e5.state, ModelUseState.notDownloaded);
    expect(m.models.first.state, ModelUseState.active);
    expect(m.models.last.builtin, isTrue);
    expect(m.byFeature('text').map((x) => x.id), ['minilm', 'e5-base']);
    expect(featureLabel('ocr'), 'Words in pictures');
    expect(tierLabel('balanced'), 'Balanced');
  });

  test('odd answers become safe defaults', () {
    final m = ModelsInfo.fromJson('nope');
    expect(m.models, isEmpty);
    expect(m.pc, isNull);
    expect(ModelInfo.fromJson({'id': 'x', 'state': 'weird'})!.state, ModelUseState.notDownloaded);
    expect(ModelUse.fromJson({'ok': false, 'error': 'e', 'needs_download': true}).needsDownload, isTrue);
    final a = AutoConfig.fromJson({
      'tier': 'light',
      'steps': [
        {'feature': 'text', 'id': 'minilm', 'needs_download': true},
      ],
    });
    expect(a.steps.single.needsDownload, isTrue);
  });

  test('the models event and the show event for the tray pages', () {
    expect((EngineEvent.parse('models', sample) as ModelsEvent).info.models, hasLength(3));
    expect((EngineEvent.parse('show', {'what': 'settings', 'text': null}) as ShowEvent).what, 'settings');
    expect((EngineEvent.parse('show', {'what': 'index', 'text': null}) as ShowEvent).what, 'index');
    expect((EngineEvent.parse('show', {'what': 'nonsense'}) as ShowEvent).what, 'main');
  });

  test('language focus, the language group of a text model, and quality scores when sent', () {
    final m = ModelsInfo.fromJson({
      ...sample,
      'language_focus': 'hindi',
      'models': [
        {
          'id': 'minilm-l6-v2',
          'feature': 'text',
          'languages': ['en'],
        },
        {
          'id': 'multilingual-e5-small',
          'feature': 'text',
          'languages': ['en', 'hi', 'multilingual (about 100 languages)'],
          'quality': {'recall5': 0.82, 'ndcg10': 0.71},
        },
        {
          'id': 'labse',
          'feature': 'text',
          'languages': ['hi', 'en', 'multilingual'],
        },
        {
          'id': 'bge-small',
          'feature': 'text',
          'languages': ['en'],
          'focus': 'english',
        },
      ],
    });
    expect(m.languageFocus, LanguageFocus.hindi);
    expect(m.models.map((x) => x.focus), [
      LanguageFocus.english,
      LanguageFocus.multilingual,
      LanguageFocus.hindi,
      LanguageFocus.english,
    ]);
    expect(m.models[1].quality!.recall5, 0.82);
    expect(m.models.first.quality, isNull);
    expect(m.models[1].languageText, 'English, Hindi, about 100 languages');
    expect(ModelsInfo.fromJson(sample).languageFocus, isNull); // an engine without it: no control shown
    expect(LanguageFocus.multilingual.wire, 'multilingual');
    expect(LanguageFocus.hindi.label, 'Hindi + English');
  });

  test('1.2: the verdict, cost and choice fields parse; an older engine sends none', () {
    final m = ModelInfo.fromJson({
      'id': 'qwen3vl-2b',
      'feature': 'talk',
      'outcome': 'upgrade',
      'why': 'Upgrade: Qwen3-VL 2B: more memory (2,491 MB)',
      'backend': 'vulkan',
      'cost_here': {'load_s': 6.21, 'answer_s': 12.08, 'ram_mb': 2491, 'shared_mb': 2058, 'measured_on': 'similar PC'},
      'fits_now': false,
      'chosen': true,
      'vectors_change': false,
    })!;
    expect(m.aboveSuggestion && !m.suggested && !m.notRecommended, isTrue);
    expect(m.cost.loadS, 6.21);
    expect(m.cost.place, 'on a similar PC');
    expect(m.cost.here, isFalse);
    expect(m.fitsNow, isFalse);
    expect(m.chosen, isTrue);
    expect(ModelInfo.fromJson({'id': 'x', 'outcome': 'not_recommended'})!.aboveSuggestion, isTrue);
    expect(ModelInfo.fromJson({'id': 'x', 'outcome': 'lighter'})!.aboveSuggestion, isFalse);
    final old = ModelInfo.fromJson({'id': 'x'})!;
    expect((old.outcome, old.why, old.fitsNow, old.chosen, old.cost.isEmpty), ('', '', null, false, true));
    expect(ModelInfo.fromJson({'id': 'x', 'cost_here': <String, Object?>{}})!.cost.isEmpty, isTrue);
    final u = ModelUse.fromJson({'ok': false, 'error': 'cost first', 'needs_download': false, 'needs_confirm': true});
    expect((u.ok, u.needsConfirm), (false, true));
    expect(ModelUse.fromJson({'ok': true}).needsConfirm, isFalse);
  });

  test('1.2: reset_suggested parses its changes with the re-index time (null: not measured)', () {
    final r = ResetSuggested.fromJson({
      'ok': true,
      'error': '',
      'applied': false,
      'changes': [
        {
          'feature': 'photo',
          'id': 'siglip2-base',
          'name': 'SigLIP 2 base',
          'from': 'siglip-base',
          'from_name': 'SigLIP base',
          'vectors_change': true,
          'index_h': 0.24,
          'measured_on': 'similar PC',
          'needs_download': true,
        },
        {'feature': 'text', 'id': 'gte-small', 'index_h': null, 'measured_on': ''},
        {'feature': 'text'},
      ],
    });
    expect(r.applied, isFalse);
    expect(r.changes.length, 2);
    expect((r.changes[0].fromName, r.changes[0].indexH, r.changes[0].vectorsChange), ('SigLIP base', 0.24, true));
    expect(r.changes[1].indexH, isNull);
  });
}
