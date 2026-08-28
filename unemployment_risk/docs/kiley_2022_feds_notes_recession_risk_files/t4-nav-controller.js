/**
 * T4 Navigation Controller (Legacy Stub)
 *
 * This is a no-op controller to maintain Angular app compatibility
 * while the actual T4 navigation functionality has been migrated to
 * vanilla JS in src/main/components/t4-nav/t4-nav.ts
 *
 * The vanilla JS will automatically clean up Angular artifacts and
 * take over the navigation enhancement.
 *
 * This stub can be removed once all pages have migrated away from
 * Angular and no longer reference the t4NavController.
 */

pubwebApp
  .controller("t4NavController", function ($scope) {
    // No-op controller - vanilla JS handles all functionality
    // This exists solely to prevent Angular bootstrap errors
  })
  .directive("expandableT4", function () {
    return {
      restrict: "A",
      link: function () {
        // No-op directive - vanilla JS handles all functionality
        // This exists solely to prevent Angular bootstrap errors
      }
    };
  });
